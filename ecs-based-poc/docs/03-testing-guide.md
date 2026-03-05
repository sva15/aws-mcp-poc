# Testing & Verification Guide

---

## Test Overview

| Category | Count | What You're Testing |
|----------|-------|---------------------|
| ALB Tool Endpoints | 8 | Tools accessible via ALB path routing |
| Tool Registry | 3 | Registry CRUD via ALB |
| MCP Server | 4 | Discovery + tool routing (cloud-agnostic) |
| Bedrock Integration | 8 | Full question→answer flow |
| Dynamic Discovery | 3 | Adding new tools via registry |
| **Total** | **26** | |

---

## 1. ALB Tool Endpoints

Test each tool Lambda via the ALB URL. This confirms ALB path routing works.

### Math Tools (`/tools/math`)

```bash
# Describe
curl -X POST http://<TOOLS-ALB-DNS>/tools/math \
  -H "Content-Type: application/json" \
  -d '{"action":"__describe__"}'

# Call: add
curl -X POST http://<TOOLS-ALB-DNS>/tools/math \
  -H "Content-Type: application/json" \
  -d '{"action":"__call__","tool":"add","arguments":{"a":10,"b":20}}'
```
✅ Describe: 4 tools | Call: `{"result":30}`

### String Tools (`/tools/string`)

```bash
curl -X POST http://<TOOLS-ALB-DNS>/tools/string \
  -H "Content-Type: application/json" \
  -d '{"action":"__call__","tool":"uppercase","arguments":{"text":"hello"}}'
```
✅ `{"result":"HELLO"}`

### DateTime Tools (`/tools/time`)

```bash
curl -X POST http://<TOOLS-ALB-DNS>/tools/time \
  -H "Content-Type: application/json" \
  -d '{"action":"__call__","tool":"current_time","arguments":{}}'
```
✅ Returns current UTC time

### Utility Tools (`/tools/utility`)

```bash
curl -X POST http://<TOOLS-ALB-DNS>/tools/utility \
  -H "Content-Type: application/json" \
  -d '{"action":"__call__","tool":"is_palindrome","arguments":{"text":"racecar"}}'
```
✅ `{"result":{"is_palindrome":true}}`

---

## 2. Tool Registry (`/registry`)

### List all providers

```bash
curl -X POST http://<TOOLS-ALB-DNS>/registry \
  -H "Content-Type: application/json" \
  -d '{"action":"list"}'
```
✅ Returns 4 providers, 14 tools with correct ALB URLs

### Register a new provider

```bash
curl -X POST http://<TOOLS-ALB-DNS>/registry \
  -H "Content-Type: application/json" \
  -d '{"action":"register","provider":{"name":"test","url":"http://example.com","tools":[{"name":"test_tool","description":"A test","input_schema":{"type":"object","properties":{}}}]}}'
```
✅ `{"status":"registered"}`

### Unregister

```bash
curl -X POST http://<TOOLS-ALB-DNS>/registry \
  -H "Content-Type: application/json" \
  -d '{"action":"unregister","name":"test"}'
```
✅ `{"status":"unregistered"}`

---

## 3. MCP Server Tests

### Health Check

```bash
curl http://10.132.191.157:8085/health
```
✅ `{"status":"healthy","tools_discovered":14,...}`

### tools/list

```bash
curl -X POST http://10.132.191.157:8085/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
✅ Returns 14 tools

### tools/call

```bash
curl -X POST http://10.132.191.157:8085/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"add","arguments":{"a":5,"b":3}}}'
```
✅ Returns `{"result":8}`

### Unknown tool

```bash
curl -X POST http://10.132.191.157:8085/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"nonexistent","arguments":{}}}'
```
✅ Returns error

---

## 4. Bedrock Integration Tests (Client Lambda)

Test via `mcp-client` Lambda console:

| # | Input | Expected |
|---|-------|----------|
| 1 | `{"action":"list_tools"}` | 14 tools |
| 2 | `{"question":"What is 15 multiplied by 27?"}` | Uses `multiply` → 405 |
| 3 | `{"question":"Convert hello to uppercase"}` | Uses `uppercase` → HELLO |
| 4 | `{"question":"What is today's date?"}` | Uses `current_time` |
| 5 | `{"question":"Convert 100 Celsius to Fahrenheit"}` | Uses `convert_temperature` → 212 |
| 6 | `{"question":"Is racecar a palindrome?"}` | Uses `is_palindrome` → true |
| 7 | `{"question":"What is the capital of France?"}` | No tool → Paris |
| 8 | `{"question":"Generate a 16-character password"}` | Uses `generate_password` |

---

## 5. Dynamic Discovery

1. **Before**: `{"action":"list_tools"}` → 14 tools
2. **Register**: Add new provider via `/registry` register action
3. **After** (wait 5 min or restart container): `{"action":"list_tools"}` → 15+ tools

---

## CloudWatch Logs

### MCP Server (`docker logs mcp-server`)

| Log | Meaning |
|-----|---------|
| `CACHE COLD START: Querying Tool Registry` | First request |
| `CACHE HIT: Using cached tool registry` | Using cache |
| `Registry returned N providers` | Registry response |
| `DISCOVERY COMPLETE: N tools from M providers` | Done |
| `INVOKE TOOL: 'add' → provider 'math-tools'` | Tool call |

### Client Lambda (`/aws/lambda/mcp-client`)

| Log | Meaning |
|-----|---------|
| `[STEP 1] Getting available tools` | Calling MCP Server |
| `[STEP 4] Bedrock wants tool: 'multiply'` | AI selected tool |
| `[DONE] Tools used: [multiply]` | Complete |
