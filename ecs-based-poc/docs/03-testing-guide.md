# Testing & Verification Guide

---

## Test Overview

| Category | Count | What You're Testing |
|----------|-------|---------------------|
| Tool Lambda Unit Tests | 16 | Each tool in isolation |
| MCP Server Tests | 5 | Discovery + tool routing |
| Bedrock Integration | 10 | Full question→answer flow |
| Dynamic Discovery | 4 | Adding/removing tools at runtime |
| **Total** | **35** | |

---

## 1. Tool Lambda Unit Tests

Test each Lambda directly in the Lambda console **Test** tab.

### mcp-tool-math (4 tools)

| # | Test Event | Expected |
|---|-----------|----------|
| 1 | `{"action": "__describe__"}` | 4 tools returned |
| 2 | `{"action":"__call__","tool":"add","arguments":{"a":10,"b":20}}` | `{"result":30}` |
| 3 | `{"action":"__call__","tool":"multiply","arguments":{"a":7,"b":6}}` | `{"result":42}` |
| 4 | `{"action":"__call__","tool":"subtract","arguments":{"a":100,"b":58}}` | `{"result":42}` |
| 5 | `{"action":"__call__","tool":"divide","arguments":{"a":10,"b":0}}` | `{"error":"Cannot divide by zero..."}` |

### mcp-tool-string (3 tools)

| # | Test Event | Expected |
|---|-----------|----------|
| 6 | `{"action": "__describe__"}` | 3 tools returned |
| 7 | `{"action":"__call__","tool":"uppercase","arguments":{"text":"hello"}}` | `{"result":"HELLO"}` |
| 8 | `{"action":"__call__","tool":"reverse","arguments":{"text":"abcdef"}}` | `{"result":"fedcba"}` |
| 9 | `{"action":"__call__","tool":"word_count","arguments":{"text":"one two three"}}` | `{"result":3}` |

### mcp-tool-time (2 tools)

| # | Test Event | Expected |
|---|-----------|----------|
| 10 | `{"action": "__describe__"}` | 2 tools returned |
| 11 | `{"action":"__call__","tool":"current_time","arguments":{}}` | Current UTC time |
| 12 | `{"action":"__call__","tool":"date_diff","arguments":{"date1":"2026-01-01","date2":"2026-12-31"}}` | `{"result":{"days":364}}` |

### mcp-tool-utility (5 tools)

| # | Test Event | Expected |
|---|-----------|----------|
| 13 | `{"action": "__describe__"}` | **5 tools** returned |
| 14 | `{"action":"__call__","tool":"convert_temperature","arguments":{"value":100,"from_unit":"celsius"}}` | `212°F` |
| 15 | `{"action":"__call__","tool":"is_palindrome","arguments":{"text":"racecar"}}` | `{"is_palindrome":true}` |
| 16 | `{"action":"__call__","tool":"generate_password","arguments":{"length":16}}` | Random password |

---

## 2. MCP Server Tests

Test via `curl` against the ALB URL.

### Test 17 — Health Check

```bash
curl http://<ALB-DNS>/health
```
✅ Returns `{"status":"healthy", "tools_discovered":14, ...}`

### Test 18 — Tool Discovery (tools/list)

```bash
curl -X POST http://<ALB-DNS>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
✅ Returns 14 tools from all 4 tool Lambdas

### Test 19 — Execute Tool (tools/call)

```bash
curl -X POST http://<ALB-DNS>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"add","arguments":{"a":5,"b":3}}}'
```
✅ Returns `{"result":8}`

### Test 20 — Unknown Tool

```bash
curl -X POST http://<ALB-DNS>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"nonexistent","arguments":{}}}'
```
✅ Returns error "Unknown tool"

### Test 21 — Unknown Method

```bash
curl -X POST http://<ALB-DNS>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"invalid/method"}'
```
✅ Returns JSON-RPC method not found error

---

## 3. Bedrock Integration Tests

Test on the `mcp-client` Lambda via the console **Test** tab.

### Test 22 — List Available Tools
```json
{"action": "list_tools"}
```
✅ Returns 14 tools from MCP Server

### Test 23 — Simple Math
```json
{"question": "What is 15 multiplied by 27?"}
```
✅ Uses `multiply`, answer contains "405"

### Test 24 — Addition
```json
{"question": "What is 1234 plus 5678?"}
```
✅ Uses `add`, answer contains "6912"

### Test 25 — String Operation
```json
{"question": "Convert 'hello world' to uppercase"}
```
✅ Uses `uppercase`, answer contains "HELLO WORLD"

### Test 26 — Word Count
```json
{"question": "How many words are in: The quick brown fox jumps over the lazy dog"}
```
✅ Uses `word_count`, answer contains "9"

### Test 27 — Current Time
```json
{"question": "What is today's date and time?"}
```
✅ Uses `current_time`

### Test 28 — Temperature Conversion
```json
{"question": "Convert 100 degrees Celsius to Fahrenheit"}
```
✅ Uses `convert_temperature`, answer contains "212"

### Test 29 — Palindrome Check
```json
{"question": "Is the word 'racecar' a palindrome?"}
```
✅ Uses `is_palindrome`, confirms yes

### Test 30 — No Tool Needed
```json
{"question": "What is the capital of France?"}
```
✅ No tools used, answers "Paris" directly

### Test 31 — Multi-Tool Question
```json
{"question": "Add 50 and 75, then tell me if the result spelled as text is a palindrome"}
```
✅ Uses `add` then `is_palindrome`, explains the result

---

## 4. Dynamic Discovery Tests

### Test 32 — Before New Tool

```json
{"action": "list_tools"}
```
✅ Note count: 14 tools

### Test 33 — Deploy New Tool Lambda

Create `mcp-tool-greeting` Lambda (see 02-deployment-guide.md for the code).

### Test 34 — After New Tool (wait for cache or force)

Wait 5 minutes (cache TTL) or test via MCP Server:
```bash
curl -X POST http://<ALB-DNS>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"force_refresh":true}}'
```
✅ Should now show **15 tools** (14 + greet)

### Test 35 — Use New Tool

```json
{"question": "Say hello to Alice"}
```
✅ Uses `greet` tool

---

## CloudWatch Log Messages to Look For

The application logs key events at every step. Here's what to look for:

### MCP Server Logs (`/ecs/mcp-server`)

| Log Pattern | What It Means |
|------------|---------------|
| `CACHE COLD START: Starting full tool discovery` | First request — scanning all Lambdas |
| `CACHE HIT: Using cached tool registry` | Subsequent request — using cache |
| `CACHE EXPIRED: Starting full tool discovery` | Cache TTL expired — re-scanning |
| `Lambda scan: found N functions` | Number of tool Lambdas found |
| `DISCOVERY COMPLETE: N tools from M Lambdas` | Discovery finished |
| `═══ HANDLE tools/list ═══` | Client requested tool list |
| `═══ HANDLE tools/call: 'add' ═══` | Client calling a tool |
| `INVOKE TOOL: 'add' → Lambda 'mcp-tool-math'` | Dispatching to tool Lambda |
| `TOOL RESULT: 'add' → {"result": 8}` | Tool returned successfully |

### Client Lambda Logs (`/aws/lambda/mcp-client`)

| Log Pattern | What It Means |
|------------|---------------|
| `[PROCESS] Starting \| Question: '...'` | New question received |
| `[STEP 1] Getting available tools` | Calling MCP Server for tools |
| `[STEP 2] Converting MCP tools → Bedrock format` | Format conversion happening |
| `[STEP 3] Bedrock call — iteration N` | Calling Bedrock AI |
| `[STEP 4] Bedrock wants tool: 'multiply'` | Bedrock selected a tool |
| `[STEP 5] Tool 'multiply' result: {"result": 405}` | Tool executed successfully |
| `[STEP 6] Sending result back to Bedrock` | Tool result going to Bedrock |
| `[DONE] Final answer: ...` | Bedrock gave final answer |
| `[DONE] Tools used: [multiply]` | Summary of tools called |

---

## Verification Checklist

| # | Test | Status |
|---|------|--------|
| 1-5 | Math tools | ☐ |
| 6-9 | String tools | ☐ |
| 10-12 | DateTime tools | ☐ |
| 13-16 | Utility tools (5 in 1 Lambda) | ☐ |
| 17-21 | MCP Server via curl | ☐ |
| 22 | Client list tools | ☐ |
| 23-29 | Bedrock questions (1 per tool type) | ☐ |
| 30 | No tool needed | ☐ |
| 31 | Multi-tool question | ☐ |
| 32-35 | Dynamic discovery | ☐ |
