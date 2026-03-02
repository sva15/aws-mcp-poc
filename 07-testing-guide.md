# Testing & Verification Guide

This document provides a complete testing plan to verify the MCP POC is working correctly.

---

## Test Stages

```
Stage 1: Unit Test Tool Lambdas (isolated)
Stage 2: Verify MCP Server Startup (ECS logs)
Stage 3: Health Check (ALB endpoint)
Stage 4: Tool Discovery (Client → MCP → Tool Lambdas)
Stage 5: Tool Invocation (Client → MCP → Tool Lambda → Result)
Stage 6: Full Integration Test
```

---

## Stage 1: Unit Test Tool Lambdas

### 1.1: Math Tools Lambda

Go to **Lambda Console** → `mcp-tool-math` → **Test** tab.

**Test A — Describe:**
```json
{
  "action": "__describe__"
}
```

**Expected response:**
```json
{
  "tools": [
    {
      "name": "add",
      "description": "Add two numbers together and return the sum",
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
      "description": "Multiply two numbers together and return the product",
      "input_schema": { "..." : "..." }
    }
  ]
}
```
✅ Verify: 2 tools returned, names are "add" and "multiply"

**Test B — Call Add:**
```json
{
  "action": "__call__",
  "tool": "add",
  "arguments": {"a": 15, "b": 25}
}
```
✅ Verify: `{"result": 40}`

**Test C — Call Multiply:**
```json
{
  "action": "__call__",
  "tool": "multiply",
  "arguments": {"a": 8, "b": 7}
}
```
✅ Verify: `{"result": 56}`

**Test D — Unknown Tool:**
```json
{
  "action": "__call__",
  "tool": "subtract",
  "arguments": {"a": 10, "b": 5}
}
```
✅ Verify: Returns `{"error": "Unknown tool: subtract"}`

---

### 1.2: String Tools Lambda

Go to **Lambda Console** → `mcp-tool-string` → **Test** tab.

**Test A — Describe:**
```json
{
  "action": "__describe__"
}
```
✅ Verify: 2 tools returned, names are "uppercase" and "reverse"

**Test B — Call Uppercase:**
```json
{
  "action": "__call__",
  "tool": "uppercase",
  "arguments": {"text": "hello mcp server"}
}
```
✅ Verify: `{"result": "HELLO MCP SERVER"}`

**Test C — Call Reverse:**
```json
{
  "action": "__call__",
  "tool": "reverse",
  "arguments": {"text": "abcdef"}
}
```
✅ Verify: `{"result": "fedcba"}`

---

## Stage 2: Verify MCP Server Startup

**Check ECS Logs:**

1. Go to **ECS Console** → `mcp-cluster` → `mcp-server-service`
2. Click on the running **Task**
3. Go to **Logs** tab

**Expected log output:**
```
INFO:mcp-server:Discovering tools from 2 Lambda functions...
INFO:mcp-server:  Querying: mcp-tool-math
INFO:mcp-server:    Registered tool: add
INFO:mcp-server:    Registered tool: multiply
INFO:mcp-server:  Querying: mcp-tool-string
INFO:mcp-server:    Registered tool: uppercase
INFO:mcp-server:    Registered tool: reverse
INFO:mcp-server:Total tools discovered: 4
INFO:mcp-server:Registered MCP tool: add
INFO:mcp-server:Registered MCP tool: multiply
INFO:mcp-server:Registered MCP tool: uppercase
INFO:mcp-server:Registered MCP tool: reverse
INFO:mcp-server:Starting MCP Server on port 8000...
```

✅ Verify: 4 tools discovered and registered, server started on port 8000.

---

## Stage 3: Health Check

### Via Browser or Curl

```bash
curl http://YOUR-ALB-DNS/health
```

**Expected response:**
```json
{
  "status": "healthy",
  "tools_count": 4,
  "tools": ["add", "multiply", "uppercase", "reverse"]
}
```

✅ Verify: Status is "healthy" and all 4 tools are listed.

### Via ALB Target Group

1. Go to **EC2 Console** → **Target Groups** → `mcp-server-tg`
2. Check **Targets** tab
3. Status should be **healthy**

---

## Stage 4: Tool Discovery via Client

1. Go to **Lambda Console** → `mcp-client` → **Test** tab
2. Create test event:
```json
{
  "action": "list_tools"
}
```
3. Click **Test**

**Expected in response body:**
```json
{
  "initialize": {
    "jsonrpc": "2.0",
    "result": {
      "capabilities": {"tools": {}},
      "serverInfo": {"name": "aws-mcp-server"}
    }
  },
  "tools_list": {
    "jsonrpc": "2.0",
    "result": {
      "tools": [
        {"name": "add", "description": "Add two numbers..."},
        {"name": "multiply", "description": "Multiply two numbers..."},
        {"name": "uppercase", "description": "Convert a string to uppercase"},
        {"name": "reverse", "description": "Reverse a string"}
      ]
    }
  }
}
```

✅ Verify:
- Initialize returns server info and capabilities
- tools_list returns all 4 tools with correct names and descriptions
- No errors in the response

---

## Stage 5: Tool Invocation via Client

### Test individual tool calls:

**Test Add:**
```json
{
  "action": "call_tool",
  "tool_name": "add",
  "arguments": {"a": 100, "b": 200}
}
```
✅ Expected: `{"result": 300}`

**Test Multiply:**
```json
{
  "action": "call_tool",
  "tool_name": "multiply",
  "arguments": {"a": 12, "b": 12}
}
```
✅ Expected: `{"result": 144}`

**Test Uppercase:**
```json
{
  "action": "call_tool",
  "tool_name": "uppercase",
  "arguments": {"text": "proof of concept"}
}
```
✅ Expected: `{"result": "PROOF OF CONCEPT"}`

**Test Reverse:**
```json
{
  "action": "call_tool",
  "tool_name": "reverse",
  "arguments": {"text": "MCP Server on AWS"}
}
```
✅ Expected: `{"result": "SWA no revreS PCM"}`

---

## Stage 6: Full Integration Test

```json
{
  "action": "full_test"
}
```

✅ **Checklist for full_test response:**

| # | Check | Expected |
|---|-------|----------|
| 1 | `initialize` succeeds | No error, server info returned |
| 2 | `tools_list` contains 4 tools | add, multiply, uppercase, reverse |
| 3 | `add(10, 20)` | `{"result": 30}` |
| 4 | `multiply(7, 6)` | `{"result": 42}` |
| 5 | `uppercase("hello mcp")` | `{"result": "HELLO MCP"}` |
| 6 | `reverse("aws lambda")` | `{"result": "adbmal swa"}` |
| 7 | No errors in any response | All responses have valid JSON |
| 8 | Lambda execution time | < 60 seconds total |

---

## Viewing Logs for Debugging

### ECS Logs (MCP Server)
1. **CloudWatch** → Log Groups → `/ecs/mcp-server`
2. Look for log streams starting with `mcp/mcp-server/...`

### Lambda Logs (Tool/Client)
1. **CloudWatch** → Log Groups → `/aws/lambda/mcp-tool-math`
2. **CloudWatch** → Log Groups → `/aws/lambda/mcp-tool-string`
3. **CloudWatch** → Log Groups → `/aws/lambda/mcp-client`

### End-to-End Request Flow in Logs

When `full_test` runs, you should see this timeline across log groups:

```
Time    Component        Log Entry
─────   ──────────────   ────────────────────────────────────
T+0ms   mcp-client       MCP Client Lambda invoked with action: full_test
T+5ms   mcp-server       Received initialize request
T+10ms  mcp-server       Received tools/list request
T+15ms  mcp-server       Received tools/call: add
T+20ms  mcp-tool-math    __call__ received for tool: add
T+25ms  mcp-server       Tool 'add' returned: {"result": 30}
T+30ms  mcp-server       Received tools/call: multiply
...
T+100ms mcp-client       All tests completed
```

---

## Test Verification Checklist

| # | Test | Status |
|---|------|--------|
| 1 | Math Lambda — __describe__ | ☐ Pass |
| 2 | Math Lambda — add | ☐ Pass |
| 3 | Math Lambda — multiply | ☐ Pass |
| 4 | String Lambda — __describe__ | ☐ Pass |
| 5 | String Lambda — uppercase | ☐ Pass |
| 6 | String Lambda — reverse | ☐ Pass |
| 7 | MCP Server — startup logs | ☐ Pass |
| 8 | MCP Server — /health endpoint | ☐ Pass |
| 9 | ALB — target healthy | ☐ Pass |
| 10 | Client — list_tools | ☐ Pass |
| 11 | Client — call_tool (each tool) | ☐ Pass |
| 12 | Client — full_test | ☐ Pass |

---

**Next:** Go to [08-production-readiness.md](./08-production-readiness.md) for production migration steps.
