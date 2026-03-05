# Architecture Overview — What Each Service Does

---

## The Big Picture

```
┌───────────┐         ┌──────────────────────────┐         ┌──────────────────────────────┐
│  CLIENT   │──JSON──▶│      MCP SERVER           │──HTTP──▶│       TOOLS ALB              │
│           │  RPC    │   (Docker container)       │         │  (path-based routing)        │
│ - Lambda  │◀────────│                            │◀────────│                              │
│ - Agent   │         │ Port 8085                  │         │ ┌──────────────────────────┐ │
│ - CLI     │         │ Endpoint: /mcp             │         │ │ /registry → Registry     │ │
│ - Any app │         │ Health:   /health           │         │ │ /tools/math → Math       │ │
└───────────┘         └──────────────────────────┘         │ │ /tools/string → String   │ │
                                                            │ │ /tools/time → DateTime   │ │
                                                            │ │ /tools/utility → Utility │ │
                                                            │ └──────────────────────────┘ │
                                                            └──────────────────────────────┘
```

---

## 1. MCP Server (Container on EC2)

**What it is**: A Docker container running on `10.132.191.157:8085` that speaks the MCP protocol (JSON-RPC 2.0 over HTTP).

**What it does**:
- Receives client requests at `/mcp` endpoint
- Handles two MCP operations:
  - `tools/list` → "What tools are available?" → asks Tool Registry
  - `tools/call` → "Execute this tool" → calls the tool's URL directly
- Caches tool definitions for 5 minutes (avoids calling registry on every request)
- Provides `/health` endpoint for monitoring

**What it does NOT do**:
- Does NOT contain any tool logic (tools live in separate Lambdas)
- Does NOT use any AWS SDK (`boto3`) — fully cloud-agnostic
- Does NOT decide which tool to use (that's the client/Bedrock's job)

**Internal modules**:

| Module | Responsibility |
|--------|---------------|
| `main.py` | Wires everything: Starlette app, /health endpoint, /mcp endpoint, startup discovery, Host header middleware |
| `server.py` | Registers `tools/list` and `tools/call` handlers with the MCP SDK |
| `discovery.py` | Calls Tool Registry via HTTP, caches results, calls tools via HTTP |
| `config.py` | Reads environment variables (REGISTRY_URL, CACHE_TTL, PORT, etc.) |

**Technology**: Python + MCP SDK (low-level Server) + FastMCP (HTTP transport only) + Starlette + uvicorn

---

## 2. Tool Registry (Lambda behind ALB at `/registry`)

**What it is**: A Lambda function that acts as a phone book — it knows which tools exist and where they live.

**What it does**:
- Stores a catalog of tool providers (name, URL, tool definitions)
- Returns the full catalog when asked (`{"action":"list"}`)
- Allows adding new providers at runtime (`{"action":"register"}`)
- Allows removing providers (`{"action":"unregister"}`)

**What it does NOT do**:
- Does NOT execute tools (MCP server calls tools directly, NOT through registry)
- Does NOT scan or discover tools automatically (providers are pre-listed or registered)

**Example response** (when MCP server calls `{"action":"list"}`):

```json
{
  "providers": [
    {
      "name": "math-tools",
      "url": "http://tools-alb/tools/math",
      "tools": [
        {"name": "add", "description": "Add two numbers...", "input_schema": {...}},
        {"name": "multiply", "description": "Multiply two numbers...", "input_schema": {...}}
      ]
    },
    {
      "name": "string-tools",
      "url": "http://tools-alb/tools/string",
      "tools": [...]
    }
  ]
}
```

---

## 3. Tool Lambdas (Behind ALB at `/tools/*`)

**What they are**: Lambda functions that do the actual work (math, string ops, etc.).

**What they do**:
- Each Lambda hosts one or more tools
- Respond to `{"action":"__describe__"}` → return their tool definitions
- Respond to `{"action":"__call__","tool":"add","arguments":{...}}` → execute the tool and return the result

**What they do NOT do**:
- Do NOT register themselves (the registry knows about them)
- Do NOT talk to the MCP server (MCP server calls them)

| Lambda | ALB Path | Tools |
|--------|----------|-------|
| `mcp-tool-math` | `/tools/math` | add, multiply, subtract, divide |
| `mcp-tool-string` | `/tools/string` | uppercase, reverse, word_count |
| `mcp-tool-time` | `/tools/time` | current_time, date_diff |
| `mcp-tool-utility` | `/tools/utility` | convert_temperature, calculate_percentage, generate_password, count_characters, is_palindrome |

---

## 4. Client Lambda (Bedrock-Powered)

**What it is**: The AI-powered "brain" that understands user questions and decides which tool to use.

**What it does**:
1. Receives a user question (e.g., "What is 15 × 27?")
2. Calls MCP Server `tools/list` → gets 14 available tools
3. Converts MCP tool format → Bedrock format (required — different protocols)
4. Sends question + tools to Bedrock AI model
5. Bedrock reads all tool descriptions and picks the right one
6. Client calls MCP Server `tools/call` with the selected tool
7. Sends tool result back to Bedrock
8. Bedrock generates a human-readable answer

**What it does NOT do**:
- Does NOT contain tool logic
- Does NOT talk to tools directly (goes through MCP Server)
- Does NOT hardcode which tool to use (Bedrock AI decides)

---

## 5. ALB (Application Load Balancer)

**What it is**: A single HTTP load balancer that routes traffic to the right Lambda based on the URL path.

**What it does**:
- Receives HTTP requests at the ALB DNS address
- Routes by path:
  - `/registry` → Tool Registry Lambda
  - `/tools/math` → Math Lambda
  - `/tools/string` → String Lambda
  - `/tools/time` → DateTime Lambda
  - `/tools/utility` → Utility Lambda

**Why one ALB**: Single entry point, easy to add new tools (just add a new path rule).

---

## How They Connect — Request Flow

```
User: "What is 15 multiplied by 27?"

1. Client Lambda receives the question
2. Client → MCP Server:  POST /mcp {"method":"tools/list"}
3.                        MCP Server → ALB /registry {"action":"list"}
4.                        ALB → Registry Lambda → returns 14 tools
5.                        MCP Server → Client: here are 14 tools
6. Client → Bedrock:     "Question + 14 tools, which one to use?"
7. Bedrock:              "Use multiply(a=15, b=27)"
8. Client → MCP Server:  POST /mcp {"method":"tools/call","params":{"name":"multiply",...}}
9.                        MCP Server → ALB /tools/math {"action":"__call__","tool":"multiply",...}
10.                       ALB → Math Lambda → {"result":405}
11.                       MCP Server → Client: {"result":405}
12. Client → Bedrock:    "Here's the result: 405. Give me a final answer."
13. Bedrock:             "15 multiplied by 27 is 405."
14. Client → User:       "15 multiplied by 27 is 405."
```

---

## Who Calls Whom

```
Client → MCP Server → Tool Registry (for discovery only)
                     → Tool Lambdas (for execution only)

Client does NOT call:
  × Tool Registry
  × Tool Lambdas
  × ALB directly

MCP Server does NOT call:
  × Bedrock (that's the client's job)
  × Any AWS SDK (cloud-agnostic)
```
