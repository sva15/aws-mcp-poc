# Execution Flow Deep Dive

This explains exactly how the code executes from container startup to answering a user question, and why we chose specific patterns.

---

## 1. `@mcp.tool()` vs Low-Level Server API

### `@mcp.tool()` — FastMCP Pattern (Static Tools)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
```

How it works:
1. FastMCP reads the `def add(a: int, b: int)` signature
2. It auto-generates JSON Schema from the type hints: `{"properties":{"a":{"type":"integer"},...}}`
3. The description comes from the docstring `"""Add two numbers."""`
4. When a client calls `tools/list`, FastMCP returns this auto-generated schema
5. When a client calls `tools/call`, FastMCP invokes the Python function directly

**When to use**: Tools are written directly inside your server code and you know all tools at code-time.

### `@server.list_tools()` — Low-Level Server Pattern (Dynamic Tools)

```python
from mcp.server.lowlevel import Server

server = Server("my-server")

@server.list_tools()
async def handle_list_tools():
    # Fetch tool definitions from external registry at RUNTIME
    tools = call_registry_http()  # ← schemas come from outside
    return tools

@server.call_tool()
async def handle_call_tool(name, arguments):
    # Route to external service via HTTP
    result = call_tool_http(name, arguments)
    return result
```

How it works:
1. You provide YOUR OWN handler for `tools/list` and `tools/call`
2. The JSON Schema comes from an external source (Tool Registry) at runtime
3. You control where tool calls go (HTTP to any URL)

**When to use**: Tools are external, dynamic, or discovered at runtime.

### Why We Use Low-Level

```
Our architecture:
  Client → MCP Server → Tool Registry (HTTP) → discovers tools at RUNTIME
                       → Tool Lambda URLs (HTTP) → executes tools at RUNTIME

Tools don't exist inside our server code — they're external HTTP services.
We can't decorate something that doesn't exist yet.

@mcp.tool() ← needs the function here → ❌ our tools are in other services
@server.list_tools() ← we provide schemas ourselves → ✅ we get schemas from registry
```

---

## 2. Container Startup — What Happens When You `docker run`

```
Step 1: Docker starts the container
Step 2: CMD runs: python -m uvicorn app.main:app --host 0.0.0.0 --port 8085
Step 3: Python imports app.main module
Step 4: Module-level code executes:
        ├── import app.config   → sets up logging, reads env vars
        ├── import app.server   → creates Server("mcp-server") instance
        ├── import app.discovery → creates httpx client, empty cache
        ├── FastMCP() created    → wraps our low-level server for HTTP transport
        └── Starlette() created  → mounts /health + /mcp routes
Step 5: uvicorn starts the ASGI server on port 8085
Step 6: Starlette lifespan starts:
        ├── Initial tool discovery (calls Tool Registry via HTTP)
        ├── Caches all tool definitions
        └── FastMCP session manager starts
Step 7: Server is ready → "Server ready to accept connections"
```

### Module Import Chain

```python
# app/main.py is the entry point
from app.config import ...     # Step 4a: logging, env vars
from app.server import server  # Step 4b: creates MCP Server instance
from app.discovery import ...  # Step 4c: creates HTTP client

# These imports trigger @server.list_tools() and @server.call_tool()
# decorators to register our handler functions
```

---

## 3. Request Lifecycle — `tools/list`

```
Client sends:
  POST http://10.132.191.157:8085/mcp
  Headers: Content-Type: application/json, Accept: application/json
  Body: {"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

Step-by-step internal flow:

```
 1. Request arrives at EC2 port 8085
 2. Docker forwards to container port 8085
 3. uvicorn receives the HTTP request
 4. HostHeaderMiddleware rewrites Host to localhost:8085
 5. Starlette routes: POST /mcp → Mount("/") → streamable_http_app()
 6. FastMCP's Streamable HTTP handler receives the request
 7. FastMCP parses JSON-RPC body → method="tools/list"
 8. FastMCP calls our @server.list_tools() handler

 9. handle_list_tools() executes:
    ├── Calls discover_tools()
    │   ├── Checks cache: is it older than CACHE_TTL_SECONDS?
    │   ├── If fresh → returns cached _tool_registry immediately
    │   └── If expired or empty:
    │       ├── HTTP POST to REGISTRY_URL {"action":"list"}
    │       │   ├── ALB receives at /registry
    │       │   ├── Routes to Tool Registry Lambda
    │       │   ├── Lambda returns {"providers":[{name, url, tools}, ...]}
    │       │   └── Response travels back to MCP server
    │       ├── Builds _tool_registry from provider data
    │       └── Updates cache timestamp
    │
    ├── Converts registry entries to MCP types.Tool objects
    └── Returns list of Tool objects

10. FastMCP wraps in JSON-RPC response:
    {"jsonrpc":"2.0","id":1,"result":{"tools":[{name, description, inputSchema}, ...]}}

11. Response sent back to client
```

---

## 4. Request Lifecycle — `tools/call`

```
Client sends:
  POST http://10.132.191.157:8085/mcp
  Body: {"jsonrpc":"2.0","id":2,"method":"tools/call",
         "params":{"name":"add","arguments":{"a":5,"b":3}}}
```

Step-by-step:

```
 1-8. Same as tools/list (routes to our handler)

 9. handle_call_tool(name="add", arguments={"a":5,"b":3}) executes:
    ├── Calls invoke_tool("add", {"a":5,"b":3})
    │   ├── Calls discover_tools() → cache hit (returns instantly)
    │   ├── Looks up "add" in _tool_registry
    │   │   → finds: {provider_url: "http://ALB/tools/math", ...}
    │   │
    │   ├── HTTP POST to http://ALB/tools/math:
    │   │   Body: {"action":"__call__","tool":"add","arguments":{"a":5,"b":3}}
    │   │   ├── ALB routes /tools/math → mcp-tool-math Lambda
    │   │   ├── Lambda detects ALB event (httpMethod present)
    │   │   ├── Parses body → action="__call__", tool="add"
    │   │   ├── Calls _execute_add(5.0, 3.0) → {"result":8, "expression":"5+3=8"}
    │   │   └── Returns ALB response: {"statusCode":200,"body":"{...}"}
    │   │
    │   ├── MCP server receives HTTP 200
    │   ├── Parses ALB response body
    │   └── Returns {"result":8,"expression":"5+3=8"}
    │
    ├── Wraps result in types.TextContent
    └── Returns [TextContent(type="text", text='{"result":8,...}')]

10. FastMCP wraps in JSON-RPC response:
    {"jsonrpc":"2.0","id":2,"result":{
      "content":[{"type":"text","text":"{\"result\":8,...}"}]
    }}

11. Response sent back to client
```

---

## 5. Full Question Flow (with Bedrock)

```
User asks: "What is 15 multiplied by 27?"
```

```
 1. Client Lambda receives {"question":"What is 15 multiplied by 27?"}

 2. [STEP 1] Client Lambda → MCP Server: tools/list
    → MCP Server returns 14 tools (from cache)

 3. [STEP 2] Client Lambda converts MCP tools → Bedrock format:
    MCP:     {"name":"multiply","inputSchema":{"properties":{...}}}
    Bedrock: {"toolSpec":{"name":"multiply","inputSchema":{"json":{"properties":{...}}}}}
    (Bedrock wraps JSON Schema inside toolSpec.inputSchema.json)

 4. [STEP 3] Client Lambda → Bedrock converse API:
    Sends: user message + 14 tool definitions
    Bedrock AI reads:
      - User intent: "15 multiplied by 27" → multiplication
      - Scans all 14 tool descriptions
      - Matches: "multiply" description says "Multiply two numbers"
      - Generates: toolUse={name:"multiply", input:{a:15, b:27}}

 5. Bedrock returns: stopReason="tool_use"

 6. [STEP 4] Client Lambda → MCP Server: tools/call multiply(a=15, b=27)
    → MCP Server → ALB /tools/math → Lambda → {"result":405}

 7. [STEP 5] Client Lambda sends tool result back to Bedrock:
    toolResult={toolUseId:"...", content:[{json:{result:405}}]}

 8. [STEP 6] Bedrock generates final answer:
    "15 multiplied by 27 is 405."
    stopReason="end_turn"

 9. Client Lambda returns:
    {"answer":"15 multiplied by 27 is 405.", "tools_used":["multiply"]}
```

---

## 6. Cloud-Agnostic Design Principles

| Principle | How We Apply It |
|-----------|----------------|
| No cloud SDK in MCP server | Removed `boto3`, only uses `httpx` for HTTP calls |
| Configuration via env vars | `REGISTRY_URL` — point to any HTTP endpoint |
| Standard protocols only | JSON-RPC 2.0 (MCP), HTTP POST (tools), JSON (everywhere) |
| Tool providers = HTTP endpoints | Works with Lambda+ALB, Azure Functions, Docker, K8s services |
| Registry is just a catalog | MCP server calls tools directly, NOT through registry |

### What changes when moving to another cloud?

| Component | AWS | Azure | GCP | On-Prem |
|-----------|-----|-------|-----|---------|
| MCP Server | EC2 + Docker | Azure VM + Docker | GCE + Docker | Any server + Docker |
| Tool Registry | Lambda + ALB | Azure Function | Cloud Function | Any HTTP service |
| Tool Providers | Lambda + ALB | Azure Functions | Cloud Functions | Any HTTP service |
| Client | Lambda + Bedrock | Azure Function + OpenAI | Cloud Function + Vertex AI | Any app + any LLM |
| **MCP Server code changes** | **None** | **None** | **None** | **None** |

The MCP server container is **identical** across all platforms. Only the URLs change.
