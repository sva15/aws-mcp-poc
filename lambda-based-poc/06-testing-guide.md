# Testing & Verification Guide

All test scenarios for the Lambda-based MCP POC.

---

## Test Categories

| Category | What You're Testing |
|----------|--------------------|
| **Unit Tests** | Each tool Lambda in isolation |
| **MCP Server Tests** | Dynamic discovery + tool execution |
| **Integration Tests** | Full flow: question → Bedrock → MCP → tool → answer |
| **Dynamic Discovery** | Adding new tools without changes |

---

## Unit Tests — Tool Lambdas

### mcp-tool-math

| # | Test Event | Expected Result |
|---|-----------|----------------|
| 1 | `{"action": "__describe__"}` | 4 tools returned |
| 2 | `{"action": "__call__", "tool": "add", "arguments": {"a": 10, "b": 20}}` | `{"result": 30}` |
| 3 | `{"action": "__call__", "tool": "multiply", "arguments": {"a": 7, "b": 6}}` | `{"result": 42}` |
| 4 | `{"action": "__call__", "tool": "subtract", "arguments": {"a": 100, "b": 58}}` | `{"result": 42}` |
| 5 | `{"action": "__call__", "tool": "divide", "arguments": {"a": 10, "b": 3}}` | `{"result": 3.333...}` |
| 6 | `{"action": "__call__", "tool": "divide", "arguments": {"a": 10, "b": 0}}` | `{"error": "Cannot divide by zero"}` |

### mcp-tool-string

| # | Test Event | Expected Result |
|---|-----------|----------------|
| 7 | `{"action": "__describe__"}` | 3 tools returned |
| 8 | `{"action": "__call__", "tool": "uppercase", "arguments": {"text": "hello"}}` | `{"result": "HELLO"}` |
| 9 | `{"action": "__call__", "tool": "reverse", "arguments": {"text": "abcdef"}}` | `{"result": "fedcba"}` |
| 10 | `{"action": "__call__", "tool": "word_count", "arguments": {"text": "one two three"}}` | `{"result": 3}` |

### mcp-tool-time

| # | Test Event | Expected Result |
|---|-----------|----------------|
| 11 | `{"action": "__describe__"}` | 2 tools returned |
| 12 | `{"action": "__call__", "tool": "current_time", "arguments": {}}` | Current UTC time |
| 13 | `{"action": "__call__", "tool": "date_diff", "arguments": {"date1": "2026-01-01", "date2": "2026-12-31"}}` | `{"result": {"days": 364}}` |
| 14 | `{"action": "__call__", "tool": "date_diff", "arguments": {"date1": "bad", "date2": "data"}}` | Error about invalid date format |

---

## MCP Server Tests

Run these on the `mcp-server` Lambda:

### Test 15 — Tool Discovery

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

✅ Must return **9 tools** from all 3 tool Lambdas

### Test 16 — Force Refresh

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"force_refresh": true}}
```

✅ Forces a fresh scan (check CloudWatch logs for "Starting tool discovery")

### Test 17 — Call Tool

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "add", "arguments": {"a": 5, "b": 3}}}
```

✅ Must return `{"result": 8}` in content

### Test 18 — Unknown Tool

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nonexistent", "arguments": {}}}
```

✅ Must return error with "Unknown tool"

---

## Integration Tests — Full Flow with Bedrock

Run these on the `mcp-client` Lambda. These are the **most important tests**.

### Test 19 — List Available Tools

```json
{"action": "list_tools"}
```

✅ Should return 9 tools from all 3 Lambda functions

### Test 20 — Simple Math Question

```json
{"question": "What is 15 multiplied by 27?"}
```

**Expected:**
- `answer`: Contains "405"
- `tools_used`: Contains `multiply` with input `{a: 15, b: 27}`
- `model`: Shows the Bedrock model used

### Test 21 — Addition

```json
{"question": "What is 1234 plus 5678?"}
```

**Expected:**
- Bedrock calls `add(1234, 5678)` → 6912
- Answer contains "6912"

### Test 22 — Division

```json
{"question": "If I divide 100 by 7, what do I get?"}
```

**Expected:**
- Bedrock calls `divide(100, 7)` → 14.2857...
- Answer contains the decimal result

### Test 23 — String Uppercase

```json
{"question": "Can you convert this to uppercase: hello world from mcp"}
```

**Expected:**
- Bedrock calls `uppercase("hello world from mcp")`
- Answer contains "HELLO WORLD FROM MCP"

### Test 24 — Word Count

```json
{"question": "How many words are in: The quick brown fox jumps over the lazy dog"}
```

**Expected:**
- Bedrock calls `word_count(...)`
- Answer contains "9"

### Test 25 — Reverse String

```json
{"question": "What is the word 'Lambda' spelled backwards?"}
```

**Expected:**
- Bedrock calls `reverse("Lambda")`
- Answer contains "adbmaL"

### Test 26 — Current Time

```json
{"question": "What is the current date and time?"}
```

**Expected:**
- Bedrock calls `current_time()`
- Answer contains UTC date/time

### Test 27 — Date Difference

```json
{"question": "How many days are between January 1, 2026 and December 31, 2026?"}
```

**Expected:**
- Bedrock calls `date_diff("2026-01-01", "2026-12-31")`
- Answer contains "364 days"

### Test 28 — No Tool Needed

```json
{"question": "What is the capital of France?"}
```

**Expected:**
- No tools used (Bedrock answers directly)
- Answer: "Paris"

### Test 29 — Multi-Tool Question

```json
{"question": "Add 50 and 75, then convert the result to a string and reverse it"}
```

**Expected:**
- Bedrock calls `add(50, 75)` → 125
- Then calls `reverse("125")` → "521"
- Answer explains both steps

---

## Dynamic Discovery Tests

### Test 30 — Before Adding New Lambda

```json
{"action": "list_tools"}
```
✅ Note the count (should be 9)

### Test 31 — Deploy New Tool Lambda

Deploy `mcp-tool-greeting` (code in deployment guide Section "Adding a New Tool")

### Test 32 — After Adding New Lambda

```json
{"action": "list_tools"}
```
✅ Count should now be 10 (includes `greet`)

### Test 33 — Use New Tool

```json
{"question": "Say hello to Alice in a casual way"}
```
✅ Bedrock should call `greet(name="Alice", style="casual")`

### Test 34 — Delete Tool Lambda

Delete `mcp-tool-greeting` from Lambda Console

### Test 35 — After Removing Lambda

Wait for cache to expire (5 min) or use force refresh, then:
```json
{"action": "list_tools"}
```
✅ Count should be back to 9

---

## Verification Checklist

| # | Test | Status |
|---|------|--------|
| 1-6 | Math tools (all 4 tools) | ☐ |
| 7-10 | String tools (all 3 tools) | ☐ |
| 11-14 | DateTime tools (both tools) | ☐ |
| 15-18 | MCP Server (discovery + execution) | ☐ |
| 19 | Client — list tools | ☐ |
| 20-27 | Bedrock questions (one per tool) | ☐ |
| 28 | No tool needed | ☐ |
| 29 | Multi-tool question | ☐ |
| 30-35 | Dynamic discovery (add/remove tool) | ☐ |

---

## Debugging Tips

### Check CloudWatch Logs

| Function | Log Group |
|----------|-----------|
| mcp-client | `/aws/lambda/mcp-client` |
| mcp-server | `/aws/lambda/mcp-server` |
| mcp-tool-math | `/aws/lambda/mcp-tool-math` |
| mcp-tool-string | `/aws/lambda/mcp-tool-string` |
| mcp-tool-time | `/aws/lambda/mcp-tool-time` |

### Common Issues

| Issue | Solution |
|-------|----------|
| "Access denied" on Bedrock | Enable model access in Bedrock console |
| "Task timed out" | Increase Lambda timeout to 120s |
| Tools not discovered | Check MCP server role has `lambda:ListFunctions` |
| Bedrock returns "I don't have tools" | Check tool descriptions are clear enough |
| Wrong model ID | Check `BEDROCK_MODEL_ID` env var matches an enabled model |
