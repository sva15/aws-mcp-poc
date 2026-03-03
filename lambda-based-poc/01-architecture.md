# Lambda-Based MCP POC with Bedrock — Architecture & Design

## 1. What This POC Does

You ask a **natural language question** → **Bedrock AI model** figures out which tool to call → **MCP server** discovers and invokes the right **tool Lambda** → you get an **intelligent answer**.

```
You: "What is 15 multiplied by 27?"

→ Client Lambda receives your question
→ Sends question + available tools to Amazon Bedrock (Claude)
→ Bedrock says: "I need to call the 'multiply' tool with a=15, b=27"
→ Client calls MCP Server Lambda with tools/call
→ MCP Server invokes the math tool Lambda
→ Math Lambda returns {"result": 405}
→ Bedrock formats the answer: "15 multiplied by 27 equals 405"
→ You get the answer back
```

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              AWS CLOUD                                  │
│                                                                         │
│  ┌─────────────────────┐         ┌────────────────────┐                │
│  │  YOU (Test Event)    │         │  AMAZON BEDROCK     │                │
│  │                     │         │  (Claude 3 Sonnet)  │                │
│  │  "What is 15 × 27?" │         │                    │                │
│  └──────────┬──────────┘         │  Decides which     │                │
│             │                    │  tool to call       │                │
│             ▼                    └────────┬───────────┘                │
│  ┌─────────────────────┐                 │                             │
│  │  CLIENT LAMBDA       │◀───────────────┘                             │
│  │  (mcp-client)        │                                              │
│  │                     │        ┌────────────────────────┐             │
│  │  1. Gets tools list  │───────▶│  MCP SERVER LAMBDA     │             │
│  │  2. Asks Bedrock     │        │  (mcp-server)          │             │
│  │  3. Calls tool       │        │                        │             │
│  │  4. Returns answer   │◀───────│  Auto-discovers tools  │             │
│  └─────────────────────┘        │  from ALL mcp-tool-*   │             │
│                                  │  Lambda functions       │             │
│                                  └───────────┬────────────┘             │
│                                              │                          │
│            ┌─────────────────────────────────┼─────────────────┐        │
│            │                                 │                 │        │
│            ▼                                 ▼                 ▼        │
│  ┌────────────────┐            ┌────────────────┐   ┌──────────────┐   │
│  │ mcp-tool-math   │            │ mcp-tool-string│   │mcp-tool-time │   │
│  │                │            │                │   │              │   │
│  │  • add          │            │  • uppercase    │   │  • now        │   │
│  │  • multiply     │            │  • reverse      │   │  • date_diff  │   │
│  │  • subtract     │            │  • word_count   │   │              │   │
│  │  • divide       │            │                │   │              │   │
│  └────────────────┘            └────────────────┘   └──────────────┘   │
│                                                                         │
│   ✨ Deploy a new mcp-tool-* Lambda → MCP Server finds it automatically │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. How Dynamic Tool Discovery Works

This is the **key innovation** — when you deploy a new tool Lambda, the MCP server finds it **automatically**. No configuration changes needed.

### The Discovery Mechanism

```
Step 1: MCP Server calls boto3 lambda.list_functions()
Step 2: Filters functions whose name starts with "mcp-tool-"
Step 3: For EACH matching Lambda:
         → Invokes it with {"action": "__describe__"}
         → Gets back the list of tools with names, descriptions, and schemas
Step 4: Builds a combined tool registry from all responses
Step 5: Returns the complete tool list to whoever asked
```

### Why Prefix-Based Discovery?

| Approach | Pros | Cons |
|----------|------|------|
| ~~Environment variable~~ | Simple | Must update env + restart on every new tool |
| ~~DynamoDB registry~~ | Flexible | Extra service, must manually register |
| **Prefix-based (our approach)** | **Zero config, fully automatic** | **Need naming convention** |
| ~~Tags-based~~ | Flexible | Slower API calls, more complex |

**Convention:** Any Lambda whose name starts with `mcp-tool-` is automatically treated as a tool provider.

### Adding a New Tool

```
1. Write a new Lambda function following the __describe__ / __call__ protocol
2. Deploy it as: mcp-tool-<anything>  (e.g., mcp-tool-weather)
3. Done! MCP Server will find it on next tools/list call
```

No restarts. No config changes. No redeployments. It just works.

---

## 4. How Bedrock Decides Which Tool to Call

Amazon Bedrock supports **tool use (function calling)**. Here's the flow:

```
┌──────────────────────────────────────────────────────────────┐
│                    BEDROCK TOOL USE FLOW                      │
│                                                              │
│  1. Client sends to Bedrock:                                 │
│     - User's question: "What is 15 × 27?"                   │
│     - Available tools: [add, multiply, subtract, ...]        │
│                                                              │
│  2. Bedrock analyzes and responds with:                      │
│     - stopReason: "tool_use"                                 │
│     - toolUse: {                                             │
│         name: "multiply",                                    │
│         input: {"a": 15, "b": 27}                            │
│       }                                                      │
│                                                              │
│  3. Client executes the tool via MCP Server:                 │
│     - Calls tools/call → multiply(15, 27) → 405             │
│                                                              │
│  4. Client sends tool result back to Bedrock:                │
│     - toolResult: {"result": 405}                            │
│                                                              │
│  5. Bedrock generates final answer:                          │
│     - "15 multiplied by 27 equals 405."                      │
└──────────────────────────────────────────────────────────────┘
```

### Bedrock Tool Specification Format

Bedrock expects tools in this format:

```json
{
    "toolSpec": {
        "name": "multiply",
        "description": "Multiply two numbers together and return the product",
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

The client automatically converts MCP tool definitions into Bedrock's format.

---

## 5. The Three Lambda Functions Explained

### Lambda 1: MCP Server (`mcp-server`)

**What it does:** Acts as the central tool registry and executor.

| Endpoint (JSON-RPC method) | What it does |
|----------------------------|-------------|
| `tools/list` | Scans all `mcp-tool-*` Lambdas, calls `__describe__` on each, returns combined tool list |
| `tools/call` | Finds which Lambda owns the requested tool, invokes it with `__call__`, returns result |

**Key feature:** No hardcoded tool list. It discovers everything dynamically at runtime.

### Lambda 2: Tool Lambdas (`mcp-tool-math`, `mcp-tool-string`, `mcp-tool-time`)

**What they do:** Each provides one or more tools.

**Protocol every tool Lambda must follow:**

```python
# When called with {"action": "__describe__"}
# → Return your tool definitions

# When called with {"action": "__call__", "tool": "add", "arguments": {"a": 5, "b": 3}}
# → Execute the tool and return the result
```

### Lambda 3: Client Lambda (`mcp-client`)

**What it does:** Ties everything together.

```
1. Receives user question
2. Calls MCP Server → tools/list → gets all available tools
3. Converts tools to Bedrock format
4. Sends question + tools to Bedrock
5. Bedrock says "call tool X with args Y"
6. Calls MCP Server → tools/call → gets result
7. Sends result back to Bedrock
8. Bedrock generates human-readable answer
9. Returns answer to user
```

---

## 6. AWS Services Used

| Service | Purpose | Cost for POC |
|---------|---------|-------------|
| **AWS Lambda** (x5) | MCP Server + 3 Tool Lambdas + Client | Free tier covers it |
| **Amazon Bedrock** | Claude 3 Sonnet for AI reasoning | Pay-per-token (~$0.003/1K input tokens) |
| **CloudWatch Logs** | Debugging | Free tier covers it |
| **IAM** | Permissions | Free |

**Estimated POC cost: < $1** (mostly Bedrock token usage)

---

## 7. IAM Permissions Summary

| Lambda | Needs Permission To | Policy |
|--------|-------------------|--------|
| `mcp-server` | List all Lambda functions | `lambda:ListFunctions` |
| `mcp-server` | Invoke tool Lambdas | `lambda:InvokeFunction` on `mcp-tool-*` |
| `mcp-client` | Invoke MCP server Lambda | `lambda:InvokeFunction` on `mcp-server` |
| `mcp-client` | Call Bedrock models | `bedrock:InvokeModel` |
| `mcp-tool-*` | Write logs only | `AWSLambdaBasicExecutionRole` |

---

## 8. File Structure

```
lambda-based-poc/
├── 01-architecture.md                 ← This document
├── 02-mcp-server.md                   ← MCP Server code explained
├── 03-tool-lambdas.md                 ← Tool Lambda code explained
├── 04-client-lambda.md                ← Client Lambda + Bedrock explained
├── 05-deployment-guide.md             ← Step-by-step AWS Console guide
├── 06-testing-guide.md                ← How to test everything
│
├── mcp-server/
│   └── lambda_function.py             ← MCP Server Lambda code
│
├── tool-lambdas/
│   ├── math_tools/
│   │   └── lambda_function.py         ← add, multiply, subtract, divide
│   ├── string_tools/
│   │   └── lambda_function.py         ← uppercase, reverse, word_count
│   └── datetime_tools/
│       └── lambda_function.py         ← now, date_diff
│
└── client-lambda/
    └── lambda_function.py             ← Bedrock-powered MCP client
```

---

## 9. Reading Order

| Step | Document | What You'll Learn |
|------|----------|-------------------|
| 1 | `01-architecture.md` | **This doc** — understand the full system |
| 2 | `02-mcp-server.md` | How the MCP server discovers tools dynamically |
| 3 | `03-tool-lambdas.md` | How to write tool Lambdas (and add new ones) |
| 4 | `04-client-lambda.md` | How Bedrock decides which tool to call |
| 5 | `05-deployment-guide.md` | Deploy everything via AWS Console |
| 6 | `06-testing-guide.md` | Test questions & expected results |

---

**Next →** [02-mcp-server.md](./02-mcp-server.md) — The MCP Server with dynamic tool discovery
