# How It Works Internally — Deep Dive

This document explains every internal mechanism: the MCP protocol, how Bedrock selects tools, why format conversion is required, and how auto-discovery works.

---

## 1. The MCP Protocol — What Actually Happens Over the Wire

MCP uses **JSON-RPC 2.0 over HTTP**. Every interaction is a simple HTTP POST with a JSON body.

### 1.1 The JSON-RPC 2.0 Message Format

Every MCP message follows this exact structure:

```
┌─────────────────────────────────────────────────────────────────────┐
│  REQUEST (Client → Server)                                          │
│                                                                     │
│  POST /mcp HTTP/1.1                                                 │
│  Content-Type: application/json                                     │
│                                                                     │
│  {                                                                  │
│      "jsonrpc": "2.0",          ← Protocol version (always "2.0")  │
│      "id": 1,                   ← Request ID (for matching resp.)  │
│      "method": "tools/list",    ← What you want to do              │
│      "params": {}               ← Parameters (optional)            │
│  }                                                                  │
├─────────────────────────────────────────────────────────────────────┤
│  RESPONSE (Server → Client)                                         │
│                                                                     │
│  HTTP 200 OK                                                        │
│  Content-Type: application/json                                     │
│                                                                     │
│  {                                                                  │
│      "jsonrpc": "2.0",          ← Protocol version                 │
│      "id": 1,                   ← Matches request ID               │
│      "result": {                ← The actual data                  │
│          "tools": [...]                                             │
│      }                                                              │
│  }                                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 The Three MCP Methods We Use

**Method 1: `initialize`** — Handshake between client and server

```json
// Request
{"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{
    "protocolVersion":"2025-03-26",
    "capabilities":{},
    "clientInfo":{"name":"my-client","version":"1.0.0"}
}}

// Response
{"jsonrpc":"2.0", "id":1, "result":{
    "protocolVersion":"2025-03-26",
    "capabilities":{"tools":{"listChanged":true}},
    "serverInfo":{"name":"mcp-server","version":"1.0.0"}
}}
```

**Method 2: `tools/list`** — Get all available tools

```json
// Request
{"jsonrpc":"2.0", "id":2, "method":"tools/list"}

// Response
{"jsonrpc":"2.0", "id":2, "result":{"tools":[
    {
        "name": "add",
        "description": "Add two numbers together",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type":"number", "description":"First number"},
                "b": {"type":"number", "description":"Second number"}
            },
            "required": ["a", "b"]
        }
    }
]}}
```

**Method 3: `tools/call`** — Execute a specific tool

```json
// Request
{"jsonrpc":"2.0", "id":3, "method":"tools/call", "params":{
    "name": "add",
    "arguments": {"a": 15, "b": 27}
}}

// Response
{"jsonrpc":"2.0", "id":3, "result":{
    "content": [{"type":"text", "text":"{\"result\": 42}"}]
}}
```

### 1.3 Streamable HTTP Transport

Our MCP server uses **Streamable HTTP** — the recommended transport for production:

```
Client                                    Server (ECS)
  │                                          │
  │  POST /mcp  {initialize}                 │
  │ ────────────────────────────────────────▶ │
  │                                          │
  │  200 OK  {serverInfo, capabilities}      │
  │ ◀──────────────────────────────────────── │
  │                                          │
  │  POST /mcp  {tools/list}                 │
  │ ────────────────────────────────────────▶ │
  │                                          │
  │  200 OK  {tools: [...]}                  │
  │ ◀──────────────────────────────────────── │
  │                                          │
  │  POST /mcp  {tools/call, name:"add"}     │
  │ ────────────────────────────────────────▶ │
  │                                          │
  │  200 OK  {content: [{text:"42"}]}        │
  │ ◀──────────────────────────────────────── │
```

We use `stateless_http=True` and `json_response=True` as per the official SDK recommendation for scalable deployments. This means:
- No session state on the server (each request is independent)
- Pure JSON responses (no SSE streaming)
- Works perfectly behind a load balancer

---

## 2. How Bedrock Selects the Right Tool

This is the most important concept to understand. **Bedrock doesn't "know" about MCP** — it's the Client Lambda that bridges them.

### 2.1 What Happens Inside Bedrock

When you call the Bedrock `converse` API with tools, here's what happens internally:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Inside Amazon Bedrock                        │
│                                                                 │
│  INPUT:                                                         │
│    User message: "What is 15 multiplied by 27?"                 │
│    Available tools:                                             │
│      - add: "Add two numbers together"                          │
│      - multiply: "Multiply two numbers and return the product"  │
│      - uppercase: "Convert a string to uppercase"               │
│      - current_time: "Get the current date and time"            │
│                                                                 │
│  BEDROCK'S REASONING:                                           │
│    1. Parse the user's intent: "multiplication of 15 and 27"    │
│    2. Match intent against tool descriptions:                   │
│       - "add" → about adding, not multiplying ❌                │
│       - "multiply" → "Multiply two numbers" ✅ MATCH            │
│       - "uppercase" → about strings, not numbers ❌             │
│       - "current_time" → about time, not math ❌                │
│    3. Extract parameters from the question:                     │
│       - a = 15 (from "15")                                      │
│       - b = 27 (from "27")                                      │
│    4. Generate tool_use response                                │
│                                                                 │
│  OUTPUT:                                                        │
│    stopReason: "tool_use"                                       │
│    toolUse: {name:"multiply", input:{a:15, b:27}}               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 How the AI Model Actually Decides

The Claude/Nova model is trained on millions of examples of function calling. It uses:

1. **Tool Name Matching** — The model compares the user's intent against tool names
2. **Description Matching** — The `description` field is the PRIMARY signal. The model reads every description to understand what each tool does
3. **Schema Understanding** — The model reads `inputSchema` to know what parameters are needed and what types they should be
4. **Contextual Reasoning** — The model uses its general knowledge to understand synonyms (e.g., "times" = "multiply", "plus" = "add")
5. **Parameter Extraction** — The model parses the user's message to extract values for the tool parameters

**This is why tool descriptions are SO important:**

```python
# ❌ BAD — Bedrock won't know when to use this
"description": "multiply"

# ✅ GOOD — Bedrock clearly understands when to use this  
"description": "Multiply two numbers together and return the product. Use this when someone asks to multiply numbers, find a product, or calculate times."
```

### 2.3 When Bedrock Does NOT Use a Tool

Bedrock can also decide **not** to use any tool:

```
User: "What is the capital of France?"

Bedrock's reasoning:
  - None of the available tools help answer this question
  - I know the answer from my training data
  - Response: "The capital of France is Paris." (stopReason: "end_turn")
```

### 2.4 Multi-Tool Reasoning

Bedrock can chain multiple tool calls:

```
User: "Add 50 and 75, then reverse the result as a string"

Iteration 1:
  Bedrock → tool_use: add(a=50, b=75)
  Client → MCP Server → Tool Lambda → result: 125
  Client → sends result back to Bedrock

Iteration 2:
  Bedrock → tool_use: reverse(text="125")
  Client → MCP Server → Tool Lambda → result: "521"
  Client → sends result back to Bedrock

Iteration 3:
  Bedrock → "50 plus 75 is 125, and reversed as a string it's 521."
  (stopReason: "end_turn")
```

---

## 3. Why Format Conversion IS Required

MCP and Bedrock are **two completely different protocols**. They define tool schemas differently. The Client Lambda must convert between them.

### 3.1 MCP Tool Format (from `tools/list`)

```json
{
    "name": "multiply",
    "description": "Multiply two numbers",
    "inputSchema": {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First number"},
            "b": {"type": "number", "description": "Second number"}
        },
        "required": ["a", "b"]
    }
}
```

### 3.2 Bedrock Tool Format (for `converse` API)

```json
{
    "toolSpec": {
        "name": "multiply",
        "description": "Multiply two numbers",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        }
    }
}
```

### 3.3 The Differences

| Field | MCP | Bedrock |
|-------|-----|---------|
| Wrapper | Direct object | Wrapped in `toolSpec` |
| Schema field | `inputSchema` (direct JSON Schema) | `inputSchema.json` (nested under `json` key) |
| Tool result | `content: [{type:"text", text:"..."}]` | `toolResult: {content: [{json: {...}}]}` |

**This conversion is NOT optional.** MCP is a protocol for tool discovery and execution. Bedrock is an AI model API with its own tool specification. The Client Lambda acts as a **bridge** between two different standards.

### 3.4 What the Client Does

```python
def mcp_to_bedrock(mcp_tool):
    """Convert MCP tool definition → Bedrock tool specification."""
    return {
        "toolSpec": {
            "name": mcp_tool["name"],
            "description": mcp_tool["description"],
            "inputSchema": {
                "json": mcp_tool["inputSchema"]  # ← Nest under "json" key
            }
        }
    }
```

This is a simple structural transformation — same data, different shape.

---

## 4. Auto-Discovery — How New Tools Are Found Automatically

### 4.1 The Discovery Mechanism

The MCP Server uses **AWS Lambda API prefix scanning**:

```
┌──────────────────────────────────────────────────────────────────┐
│  MCP SERVER STARTUP / TOOL DISCOVERY                             │
│                                                                  │
│  Step 1: Call AWS API → lambda:ListFunctions                     │
│          Returns ALL Lambda functions in the account             │
│                                                                  │
│  Step 2: Filter by prefix "mcp-tool-"                            │
│          mcp-tool-math     ✅ matches                            │
│          mcp-tool-string   ✅ matches                            │
│          mcp-tool-time     ✅ matches                            │
│          mcp-server        ❌ doesn't match                      │
│          mcp-client        ❌ doesn't match                      │
│          other-function    ❌ doesn't match                      │
│                                                                  │
│  Step 3: For EACH matching Lambda, invoke with __describe__      │
│          mcp-tool-math → {"tools": [add, multiply, ...]}        │
│          mcp-tool-string → {"tools": [uppercase, reverse, ...]}  │
│                                                                  │
│  Step 4: Build combined registry                                 │
│          {                                                       │
│            "add": {lambda: "mcp-tool-math", schema: {...}},      │
│            "multiply": {lambda: "mcp-tool-math", schema: {...}}, │
│            "uppercase": {lambda: "mcp-tool-string", ...},        │
│            ...                                                   │
│          }                                                       │
│                                                                  │
│  Step 5: Register each tool with the MCP Server's Tool handler   │
│          The Server's @server.list_tools() returns this registry  │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Caching Strategy

Discovery is expensive (N Lambda invocations). So we cache:

| Event | Discovery Action |
|-------|-----------------|
| Container starts | Full discovery |
| Client calls `tools/list` within TTL | Return cached tools |
| Cache TTL expires (5 min default) | Re-discover on next request |
| Force refresh flag | Immediate re-discovery |

### 4.3 Adding a New Tool — What Happens

```
Time 0:00 — You deploy mcp-tool-weather Lambda
Time 0:01 — Someone calls tools/list (cache still valid) → 9 tools (old)
Time 5:01 — Cache expires → next tools/list triggers re-discovery → 14 tools (new!)
Time 5:02 — mcp-tool-weather is now in the registry → Bedrock can use it
```

Or with force refresh:
```
Time 0:00 — You deploy mcp-tool-weather Lambda
Time 0:01 — Call tools/list with force_refresh=true → re-discovery → 14 tools immediately
```

### 4.4 Why Prefix-Based Discovery Is Best for ECS

| Approach | ECS Compatibility | Why |
|----------|-------------------|-----|
| **Prefix scanning** ✅ | Perfect | No env var changes, no container restart needed |
| Environment variable | OK | Requires ECS task definition update + service restart |
| DynamoDB registry | OK | Extra service to manage, more complexity |
| Tags-based | Slower | `ListTags` API adds latency per function |

---

## 5. The MCP Server Architecture (Low-Level Server API)

We use the **low-level `Server` class** from the official MCP SDK instead of `FastMCP`. Here's why:

### 5.1 Why Low-Level Server, Not FastMCP?

| FastMCP | Low-Level Server |
|---------|-----------------|
| `@mcp.tool()` generates schema FROM function signature | We provide our OWN schema from Lambda `__describe__` |
| Great for static tools (known at code time) | Perfect for dynamic tools (discovered at runtime) |
| Schema = Python type hints → JSON Schema | Schema = whatever the tool Lambda tells us |

**Our tools come from Lambda functions at runtime.** We don't know their schemas when writing the server code. The low-level `Server` class lets us control the schema ourselves.

### 5.2 Official MCP SDK Pattern We Follow

From the official docs (`mcp.server.lowlevel`):

```python
from mcp.server.lowlevel import Server
import mcp.types as types

server = Server("mcp-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    # Return Tool objects with OUR schemas from Lambda discovery
    return [
        types.Tool(
            name="add",
            description="Add two numbers",
            inputSchema={
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Dispatch to the correct Lambda
    result = invoke_tool_lambda(name, arguments)
    return [types.TextContent(type="text", text=json.dumps(result))]
```

Then we run it with `FastMCP`'s Streamable HTTP transport using stateless mode.

---

## 6. The Complete Flow — End to End

```
                                            Time →
 ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐
 │  User    │  │ Client  │  │ Bedrock  │  │  MCP     │  │ Tool   │
 │          │  │ Lambda  │  │ (Claude) │  │ Server   │  │ Lambda │
 └────┬─────┘  └────┬────┘  └────┬─────┘  └────┬─────┘  └───┬────┘
      │             │            │             │             │
 1.   │ "15 × 27?"  │            │             │             │
      │────────────▶│            │             │             │
      │             │            │             │             │
 2.   │             │ tools/list │             │             │
      │             │───────────────────────▶│             │
      │             │            │             │ __describe__│
      │             │            │             │────────────▶│
      │             │            │             │◀────────────│
      │             │◀───────────────────────│  tools list │
      │             │            │             │             │
 3.   │             │ converse() │             │             │
      │             │ (question  │             │             │
      │             │  + tools)  │             │             │
      │             │───────────▶│             │             │
      │             │            │             │             │
 4.   │             │ tool_use:  │             │             │
      │             │ multiply   │             │             │
      │             │ {a:15,b:27}│             │             │
      │             │◀───────────│             │             │
      │             │            │             │             │
 5.   │             │ tools/call(multiply)     │             │
      │             │───────────────────────▶│             │
      │             │            │             │ __call__    │
      │             │            │             │ multiply    │
      │             │            │             │────────────▶│
      │             │            │             │◀────────────│
      │             │◀───────────────────────│  result:405 │
      │             │            │             │             │
 6.   │             │ converse() │             │             │
      │             │ (tool      │             │             │
      │             │  result)   │             │             │
      │             │───────────▶│             │             │
      │             │            │             │             │
 7.   │             │ "15 × 27   │             │             │
      │             │  = 405"    │             │             │
      │             │◀───────────│             │             │
      │             │            │             │             │
 8.   │ "15 × 27    │            │             │             │
      │  equals 405"│            │             │             │
      │◀────────────│            │             │             │
```

### Steps Explained

| Step | Component | Action | Log Message |
|------|-----------|--------|-------------|
| 1 | User → Client | Send question | `[CLIENT] Received question: "15 × 27?"` |
| 2 | Client → MCP Server | `tools/list` request | `[SERVER] tools/list → discovered 14 tools` |
| 3 | Client → Bedrock | Send question + tools | `[CLIENT] Asking Bedrock with 14 tools` |
| 4 | Bedrock → Client | `tool_use: multiply` | `[CLIENT] Bedrock wants tool: multiply(a=15, b=27)` |
| 5 | Client → MCP Server → Tool Lambda | Execute tool | `[SERVER] tools/call → multiply → mcp-tool-math` |
| 6 | Client → Bedrock | Send tool result | `[CLIENT] Sending result 405 back to Bedrock` |
| 7 | Bedrock → Client | Final answer | `[CLIENT] Bedrock final answer: "15 × 27 = 405"` |
| 8 | Client → User | Return answer | `[CLIENT] Done. Tools used: [multiply]` |

---

## 7. ECS Deployment — Why This Architecture

### 7.1 Why ECS Fargate for the MCP Server

| Feature | Why It Matters |
|---------|---------------|
| **Always-on** | Tool registry cached in memory, no cold start re-discovery |
| **HTTP server** | Native Streamable HTTP support, no workarounds |
| **Scalable** | ALB distributes traffic, auto-scaling adds containers |
| **Observable** | Container exec for debugging, CloudWatch Container Insights |
| **Stateless mode** | Each request independent — works behind load balancer |

### 7.2 Network Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  AWS Account                                                     │
│                                                                  │
│  ┌──────────┐     ┌──────────┐     ┌─────────────────────────┐  │
│  │ Client   │     │   ALB    │     │    ECS Fargate          │  │
│  │ Lambda   │────▶│ Port 80  │────▶│    Port 8000            │  │
│  │          │     │          │     │                         │  │
│  │          │     │ Health:  │     │  MCP Server Container   │  │
│  │          │     │ /health  │     │  - /mcp endpoint        │  │
│  └──────────┘     └──────────┘     │  - /health endpoint     │  │
│                                     │  - Tool discovery       │  │
│                                     └───────────┬─────────────┘  │
│                                                 │                │
│                                     ┌───────────┼─────────────┐  │
│                                     │   Tool Lambda Functions  │  │
│                                     │   mcp-tool-math          │  │
│                                     │   mcp-tool-string        │  │
│                                     │   mcp-tool-time          │  │
│                                     │   mcp-tool-utility       │  │
│                                     └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Stateless HTTP Mode

We configure the MCP server with `stateless_http=True`:
- **No session management** on the server
- Each HTTP request is independent
- **Perfect for load balancing** — any container can handle any request
- ECS can scale to multiple containers without session affinity

---

## 8. The Tool Lambda Protocol — `__describe__` / `__call__`

This is our **custom protocol** for tool Lambdas. It's NOT part of the MCP spec — it's how our MCP server communicates with its tool backends.

### 8.1 `__describe__` — Tell Me What Tools You Have

```python
# MCP Server sends:
{"action": "__describe__"}

# Tool Lambda responds:
{
    "tools": [
        {
            "name": "add",
            "description": "Add two numbers together. Use this when someone asks to add or sum numbers.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        },
        {
            "name": "multiply",
            "description": "Multiply two numbers. Use when someone asks to multiply or find a product.",
            "input_schema": { ... }
        }
    ]
}
```

### 8.2 `__call__` — Execute a Specific Tool

```python
# MCP Server sends:
{"action": "__call__", "tool": "add", "arguments": {"a": 15, "b": 27}}

# Tool Lambda responds:
{"result": 42}

# Or on error:
{"error": "Cannot divide by zero"}
```

### 8.3 Why This Protocol?

Each Lambda can host **multiple tools** because:
- Related tools share code (e.g., all math operations)
- Fewer Lambda functions to manage
- Shared dependencies and initialization

---

**Next →** [02-deployment-guide.md](./02-deployment-guide.md) — Deploy everything via AWS Console
