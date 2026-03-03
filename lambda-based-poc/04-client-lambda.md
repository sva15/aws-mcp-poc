# Client Lambda with Bedrock — How It All Comes Together

This document explains the client Lambda in detail — the piece that ties MCP tools with Amazon Bedrock's AI reasoning.

---

## What Happens When You Ask a Question

Let's trace through a real example: `"What is 15 multiplied by 27?"`

```
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 1: Get Available Tools                                         │
│                                                                      │
│  Client ──tools/list──▶ MCP Server ──__describe__──▶ mcp-tool-math  │
│                                      ──__describe__──▶ mcp-tool-string│
│                                      ──__describe__──▶ mcp-tool-time │
│                                                                      │
│  Result: 9 tools available (add, multiply, subtract, divide,         │
│          uppercase, reverse, word_count, current_time, date_diff)     │
├──────────────────────────────────────────────────────────────────────┤
│  STEP 2: Ask Bedrock                                                 │
│                                                                      │
│  Client sends to Bedrock:                                            │
│    • System prompt: "You are a helpful assistant with tools..."      │
│    • User message: "What is 15 multiplied by 27?"                   │
│    • Available tools: [add, multiply, subtract, divide, ...]         │
│                                                                      │
│  Bedrock responds:                                                   │
│    • stopReason: "tool_use"                                          │
│    • toolUse: {name: "multiply", input: {a: 15, b: 27}}             │
├──────────────────────────────────────────────────────────────────────┤
│  STEP 3: Execute Tool                                                │
│                                                                      │
│  Client ──tools/call("multiply", {a:15, b:27})──▶ MCP Server        │
│  MCP Server ──__call__──▶ mcp-tool-math                              │
│  mcp-tool-math returns: {"result": 405}                              │
├──────────────────────────────────────────────────────────────────────┤
│  STEP 4: Send Result Back to Bedrock                                 │
│                                                                      │
│  Client sends: toolResult = {"result": 405}                          │
│  Bedrock responds:                                                   │
│    • stopReason: "end_turn"                                          │
│    • text: "15 multiplied by 27 equals 405."                         │
├──────────────────────────────────────────────────────────────────────┤
│  STEP 5: Return to User                                              │
│                                                                      │
│  {                                                                   │
│    "answer": "15 multiplied by 27 equals 405.",                      │
│    "tools_used": [                                                   │
│      {"tool": "multiply", "input": {"a": 15, "b": 27},              │
│       "output": {"result": 405}}                                     │
│    ],                                                                │
│    "model": "anthropic.claude-3-sonnet-20240229-v1:0"                │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## The Bedrock Tool Use Cycle

Bedrock's tool use is a **conversation loop**, not a single call:

```
             ┌────────────────────────────────────────┐
             │                                        │
             ▼                                        │
  ┌──────────────────┐                               │
  │ Send question +   │                               │
  │ tools to Bedrock  │                               │
  └────────┬─────────┘                               │
           │                                          │
           ▼                                          │
  ┌──────────────────┐                               │
  │ Check stopReason  │                               │
  └────────┬─────────┘                               │
           │                                          │
     ┌─────┴─────┐                                   │
     │           │                                    │
     ▼           ▼                                    │
  "end_turn"  "tool_use"                             │
     │           │                                    │
     ▼           ▼                                    │
  Return      Execute tool                           │
  answer      via MCP Server                         │
              │                                       │
              ▼                                       │
           Send result                                │
           back to Bedrock ───────────────────────────┘
```

The loop continues until Bedrock gives a final text answer (`stopReason: "end_turn"`).

### Why a Loop?

Bedrock might need **multiple tools** to answer one question:

```
User: "Add 10 and 20, then multiply the result by 3"

Iteration 1:
  Bedrock → call "add" with {a: 10, b: 20}
  Result: 30

Iteration 2:
  Bedrock → call "multiply" with {a: 30, b: 3}
  Result: 90

Iteration 3:
  Bedrock → "10 plus 20 is 30, and 30 multiplied by 3 is 90."
```

---

## MCP-to-Bedrock Tool Format Conversion

The MCP server returns tools in MCP format. Bedrock expects a different format. The client converts between them:

### MCP Format (from `tools/list`)
```json
{
    "name": "multiply",
    "description": "Multiply two numbers together",
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

### Bedrock Tool Spec Format (what we send to `converse`)

```json
{
    "toolSpec": {
        "name": "multiply",
        "description": "Multiply two numbers together",
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

The key difference: Bedrock wraps the schema inside `toolSpec.inputSchema.json`.

---

## The Three Modes of the Client

The client supports three input modes:

### Mode 1: Ask a Question (Default) — Bedrock AI

```json
{"question": "What is the current time?"}
```

**Flow:** Question → Bedrock → Tool → Bedrock → Answer

### Mode 2: List Tools — Debug only

```json
{"action": "list_tools"}
```

**Flow:** Direct call to MCP Server → returns tool list

### Mode 3: Call Tool Directly — Bypass Bedrock

```json
{
    "action": "call_tool",
    "tool_name": "add", 
    "arguments": {"a": 5, "b": 3}
}
```

**Flow:** Direct call to MCP Server → executes tool → returns result

---

## Bedrock Model Selection

The `BEDROCK_MODEL_ID` environment variable controls which model to use:

| Model ID | Model | Cost | Quality |
|----------|-------|------|---------|
| `anthropic.claude-3-sonnet-20240229-v1:0` | Claude 3 Sonnet | $0.003/1K input | Great for POC |
| `anthropic.claude-3-haiku-20240307-v1:0` | Claude 3 Haiku | $0.00025/1K input | Cheapest, fast |
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | Claude 3.5 Sonnet v2 | $0.003/1K input | Best quality |
| `amazon.nova-lite-v1:0` | Amazon Nova Lite | $0.00006/1K input | Cheapest overall |
| `amazon.nova-pro-v1:0` | Amazon Nova Pro | $0.0008/1K input | Good balance |

> **POC Recommendation:** Start with `claude-3-sonnet` or `amazon.nova-lite-v1:0` (cheapest). You can change models by updating the environment variable — no code changes needed.

### Bedrock Model Access

Before using any model, you must **enable access** in the Bedrock console:

1. Go to **Amazon Bedrock Console**
2. Click **Model access** in the left sidebar
3. Click **Manage model access**
4. Select the models you want to use
5. Click **Request model access**
6. Wait for approval (usually instant for most models)

---

## Error Handling

| Scenario | What Happens |
|----------|-------------|
| No tools available | Bedrock answers without tools (plain text) |
| Tool execution fails | Error returned to Bedrock, it tries to answer anyway |
| Bedrock can't decide | Returns text saying it's unsure |
| Max iterations reached | Returns partial result with tools used so far |
| Bedrock timeout | Lambda returns error |
| MCP server unavailable | Lambda returns error |

---

## Complete Code

See: `client-lambda/lambda_function.py`

The code is organized into these sections:

1. **Configuration** — Environment variables and AWS clients
2. **MCP Server Communication** — `call_mcp_server()`, `get_available_tools()`, `execute_tool()`
3. **Bedrock Integration** — `mcp_tools_to_bedrock_format()`, `ask_bedrock()`
4. **Orchestration Loop** — `process_question()` — the main tool use cycle
5. **Lambda Entry Point** — `lambda_handler()` — routes input to the right mode

---

**Next →** [05-deployment-guide.md](./05-deployment-guide.md) — Deploy everything via AWS Console
