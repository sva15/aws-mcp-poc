# AWS Console Deployment Guide — Lambda-Based MCP POC

Step-by-step instructions to deploy everything using the AWS Console.

---

## Deployment Order

```
Step 1: Enable Bedrock Model Access
Step 2: Create IAM Roles
Step 3: Deploy Tool Lambda Functions (x4)
Step 4: Test Tool Lambdas
Step 5: Deploy MCP Server Lambda
Step 6: Test MCP Server
Step 7: Deploy Client Lambda
Step 8: Test End-to-End
```

**Estimated time: 30-45 minutes**

---

## Step 1: Enable Bedrock Model Access

> This is REQUIRED before the client Lambda can call Bedrock.

1. Go to **Amazon Bedrock Console** → [https://console.aws.amazon.com/bedrock](https://console.aws.amazon.com/bedrock)
2. Select your region (e.g., `us-east-1`)
3. Click **Model access** in the left sidebar
4. Click **Manage model access**
5. Check the box next to **Anthropic → Claude 3 Sonnet** (or whichever model you want)
6. Click **Request model access**
7. Wait for status to show **Access granted** (usually instant)

> [!IMPORTANT]
> If you prefer a cheaper model, enable **Amazon Nova Lite** instead and update the `BEDROCK_MODEL_ID` env var in Step 7 to `amazon.nova-lite-v1:0`.

---

## Step 2: Create IAM Roles

### 2A: Tool Lambda Role

1. Go to **IAM Console** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Lambda**
3. **Permissions**: Attach `AWSLambdaBasicExecutionRole`
4. **Role name**: `mcp-tool-lambda-role`
5. Click **Create Role**

### 2B: MCP Server Lambda Role

1. Go to **IAM Console** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Lambda**
3. **Permissions**: 
   - Attach `AWSLambdaBasicExecutionRole`
   - Click **Add permissions** → **Create inline policy** → **JSON**:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ListLambdaFunctions",
            "Effect": "Allow",
            "Action": "lambda:ListFunctions",
            "Resource": "*"
        },
        {
            "Sid": "InvokeToolLambdas",
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": "arn:aws:lambda:*:*:function:mcp-tool-*"
        }
    ]
}
```

4. **Policy name**: `mcp-server-policy`
5. **Role name**: `mcp-server-lambda-role`
6. Click **Create Role**

### 2C: Client Lambda Role

1. Go to **IAM Console** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Lambda**
3. **Permissions**: 
   - Attach `AWSLambdaBasicExecutionRole`
   - Click **Add permissions** → **Create inline policy** → **JSON**:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "InvokeMCPServer",
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": "arn:aws:lambda:*:*:function:mcp-server"
        },
        {
            "Sid": "InvokeBedrock",
            "Effect": "Allow",
            "Action": "bedrock:InvokeModel",
            "Resource": "arn:aws:bedrock:*::foundation-model/*"
        }
    ]
}
```

> [!NOTE]
> The Bedrock `InvokeModel` permission uses the `bedrock:InvokeModel` action. The `converse` API that our code uses requires this same permission.

4. **Policy name**: `mcp-client-policy`
5. **Role name**: `mcp-client-lambda-role`
6. Click **Create Role**

### Roles Summary

| Role | Used By | Key Permissions |
|------|---------|----------------|
| `mcp-tool-lambda-role` | Tool Lambdas | CloudWatch Logs |
| `mcp-server-lambda-role` | MCP Server | List + Invoke Lambda functions |
| `mcp-client-lambda-role` | Client Lambda | Invoke MCP Server + Bedrock |

---

## Step 3: Deploy Tool Lambda Functions

### 3A: Math Tools Lambda

1. Go to **Lambda Console** → **Create Function**
2. **Function name**: `mcp-tool-math` ⚠️ Name MUST start with `mcp-tool-`
3. **Runtime**: Python 3.12
4. **Architecture**: x86_64
5. **Permissions**: Use existing role → `mcp-tool-lambda-role`
6. Click **Create Function**
7. In the **Code** tab, replace ALL code with the contents of:
   `tool-lambdas/math_tools/lambda_function.py`
8. Click **Deploy**

### 3B: String Tools Lambda

1. **Function name**: `mcp-tool-string`
2. Same settings as above
3. Use code from: `tool-lambdas/string_tools/lambda_function.py`
4. Click **Deploy**

### 3C: DateTime Tools Lambda

1. **Function name**: `mcp-tool-time`
2. Same settings as above
3. Use code from: `tool-lambdas/datetime_tools/lambda_function.py`
4. Click **Deploy**

### 3D: Utility Tools Lambda (5 tools in ONE Lambda!)

This Lambda demonstrates **multiple diverse tools in a single Lambda function**.

1. **Function name**: `mcp-tool-utility`
2. Same settings as above (Python 3.12, `mcp-tool-lambda-role`)
3. Use code from: `tool-lambdas/utility_tools/lambda_function.py`
4. Click **Deploy**

**Tools provided by this single Lambda:**

| # | Tool | What It Does |
|---|------|--------------|
| 1 | `convert_temperature` | Convert between Celsius and Fahrenheit |
| 2 | `calculate_percentage` | What percent / percent of calculations |
| 3 | `generate_password` | Generate random secure passwords |
| 4 | `count_characters` | Count characters, letters, digits in text |
| 5 | `is_palindrome` | Check if a word/phrase is a palindrome |

---

## Step 4: Test Tool Lambdas

Test each Lambda before proceeding.

### Test mcp-tool-math

Go to **Lambda Console** → `mcp-tool-math` → **Test** tab

**Test 1 — Describe:**
```json
{"action": "__describe__"}
```
✅ Should return 4 tools: add, multiply, subtract, divide

**Test 2 — Call Add:**
```json
{"action": "__call__", "tool": "add", "arguments": {"a": 5, "b": 3}}
```
✅ Should return `{"result": 8}`

### Test mcp-tool-string

**Test 1 — Describe:**
```json
{"action": "__describe__"}
```
✅ Should return 3 tools: uppercase, reverse, word_count

**Test 2 — Call Uppercase:**
```json
{"action": "__call__", "tool": "uppercase", "arguments": {"text": "hello world"}}
```
✅ Should return `{"result": "HELLO WORLD"}`

### Test mcp-tool-time

**Test 1 — Describe:**
```json
{"action": "__describe__"}
```
✅ Should return 2 tools: current_time, date_diff

**Test 2 — Call Current Time:**
```json
{"action": "__call__", "tool": "current_time", "arguments": {}}
```
✅ Should return current UTC date/time

### Test mcp-tool-utility (5 tools in one Lambda!)

**Test 1 — Describe:**
```json
{"action": "__describe__"}
```
✅ Should return **5 tools**: convert_temperature, calculate_percentage, generate_password, count_characters, is_palindrome

**Test 2 — Convert Temperature:**
```json
{"action": "__call__", "tool": "convert_temperature", "arguments": {"value": 100, "from_unit": "celsius"}}
```
✅ Should return `212°F`

**Test 3 — Calculate Percentage:**
```json
{"action": "__call__", "tool": "calculate_percentage", "arguments": {"operation": "percent_of", "a": 20, "b": 150}}
```
✅ Should return `30`

**Test 4 — Is Palindrome:**
```json
{"action": "__call__", "tool": "is_palindrome", "arguments": {"text": "racecar"}}
```
✅ Should return `{"is_palindrome": true}`

> [!IMPORTANT]
> Do NOT proceed until all **4** tool Lambdas pass their tests!

---

## Step 5: Deploy MCP Server Lambda

1. Go to **Lambda Console** → **Create Function**
2. **Function name**: `mcp-server`
3. **Runtime**: Python 3.12
4. **Architecture**: x86_64
5. **Permissions**: Use existing role → `mcp-server-lambda-role`
6. Click **Create Function**
7. In the **Code** tab, replace ALL code with the contents of:
   `mcp-server/lambda_function.py`
8. Click **Deploy**

### Configure:

9. Go to **Configuration** → **General configuration** → **Edit**
   - **Timeout**: `120 seconds` (discovery involves invoking multiple Lambdas)
   - **Memory**: `256 MB`
   - Click **Save**

10. Go to **Configuration** → **Environment variables** → **Edit**

| Key | Value |
|-----|-------|
| `AWS_REGION` | `us-east-1` (or your region) |
| `TOOL_PREFIX` | `mcp-tool-` |
| `CACHE_TTL` | `300` |

11. Click **Save**

---

## Step 6: Test MCP Server

### Test 1 — List Tools (Dynamic Discovery)

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
}
```

**Expected response (inside body):**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {"name": "add", "description": "Add two numbers..."},
            {"name": "multiply", "description": "Multiply two numbers..."},
            {"name": "subtract", "description": "Subtract..."},
            {"name": "divide", "description": "Divide..."},
            {"name": "uppercase", "description": "Convert to uppercase..."},
            {"name": "reverse", "description": "Reverse a string..."},
            {"name": "word_count", "description": "Count words..."},
            {"name": "current_time", "description": "Get current time..."},
            {"name": "date_diff", "description": "Calculate days between..."},
            {"name": "convert_temperature", "description": "Convert temperature..."},
            {"name": "calculate_percentage", "description": "Calculate percentages..."},
            {"name": "generate_password", "description": "Generate password..."},
            {"name": "count_characters", "description": "Count characters..."},
            {"name": "is_palindrome", "description": "Check palindrome..."}
        ]
    }
}
```

✅ All **14 tools** should appear (discovered from all 4 tool Lambdas)

### Test 2 — Call a Tool

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "multiply", "arguments": {"a": 7, "b": 6}}
}
```

✅ Should return `{"result": 42}` inside the content

---

## Step 7: Deploy Client Lambda

1. Go to **Lambda Console** → **Create Function**
2. **Function name**: `mcp-client`
3. **Runtime**: Python 3.12
4. **Architecture**: x86_64
5. **Permissions**: Use existing role → `mcp-client-lambda-role`
6. Click **Create Function**
7. In the **Code** tab, replace ALL code with the contents of:
   `client-lambda/lambda_function.py`
8. Click **Deploy**

### Configure:

9. Go to **Configuration** → **General configuration** → **Edit**
   - **Timeout**: `120 seconds` (Bedrock calls can take time)
   - **Memory**: `256 MB`
   - Click **Save**

10. Go to **Configuration** → **Environment variables** → **Edit**

| Key | Value |
|-----|-------|
| `AWS_REGION` | `us-east-1` (or your region) |
| `MCP_SERVER_FUNCTION` | `mcp-server` |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-sonnet-20240229-v1:0` |

> **Alternative model IDs:** `anthropic.claude-3-haiku-20240307-v1:0` (cheapest Claude), `amazon.nova-lite-v1:0` (cheapest overall)

11. Click **Save**

---

## Step 8: Test End-to-End

### Test 1: List Tools

```json
{"action": "list_tools"}
```
✅ Should list all **14 tools** from 4 tool Lambdas

### Test 2: Ask a Math Question

```json
{"question": "What is 15 multiplied by 27?"}
```
✅ Should return "405" with `tools_used: ["multiply"]`

### Test 3: Ask a String Question

```json
{"question": "How many words are in this sentence: The quick brown fox jumps over the lazy dog"}
```
✅ Should return "9 words" with `tools_used: ["word_count"]`

### Test 4: Ask a Time Question

```json
{"question": "What is today's date and time?"}
```
✅ Should return current date/time with `tools_used: ["current_time"]`

### Test 5: Complex Multi-Tool Question

```json
{"question": "Add 100 and 200, then tell me how to spell the result backwards"}
```
✅ Should use `add` then `reverse` and give the answer

### Test 6: Temperature Conversion (from Utility Lambda)

```json
{"question": "Convert 100 degrees Celsius to Fahrenheit"}
```
✅ Should use `convert_temperature` and return 212°F

### Test 7: Percentage (from Utility Lambda)

```json
{"question": "What is 20 percent of 150?"}
```
✅ Should use `calculate_percentage` and return 30

### Test 8: Password (from Utility Lambda)

```json
{"question": "Generate a 16 character password for me"}
```
✅ Should use `generate_password` and return a random password

### Test 9: Palindrome Check (from Utility Lambda)

```json
{"question": "Is the word racecar a palindrome?"}
```
✅ Should use `is_palindrome` and confirm yes

---

## Adding a New Tool (Dynamic Discovery Test)

This is the most important test — proving that new tools are discovered automatically.

### Step 1: Create a new tool Lambda

Go to **Lambda Console** → **Create Function**

**Function name**: `mcp-tool-greeting`
**Runtime**: Python 3.12
**Role**: `mcp-tool-lambda-role`

**Code:**
```python
import json

def lambda_handler(event, context):
    action = event.get("action", "")
    if action == "__describe__":
        return {
            "tools": [{
                "name": "greet",
                "description": "Generate a personalized greeting for someone. Use this when someone asks you to greet or say hello to a person.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Person's name"},
                        "style": {"type": "string", "description": "Greeting style: formal or casual", "enum": ["formal", "casual"]}
                    },
                    "required": ["name"]
                }
            }]
        }
    elif action == "__call__":
        args = event.get("arguments", {})
        name = args.get("name", "Friend")
        style = args.get("style", "casual")
        if style == "formal":
            return {"result": f"Good day, {name}. It is a pleasure to make your acquaintance."}
        else:
            return {"result": f"Hey {name}! What's up? 👋"}
    return {"error": f"Unknown action: {action}"}
```

### Step 2: Deploy and verify

Click **Deploy**, then test:
```json
{"action": "__describe__"}
```

### Step 3: Test discovery

Go to `mcp-client` → Test:
```json
{"action": "list_tools"}
```
✅ Should now show **15 tools** (14 original + greet)

### Step 4: Ask a question

```json
{"question": "Please greet John in a formal way"}
```
✅ Should use the `greet` tool and return a formal greeting

**You just added a new tool with ZERO changes to the MCP server or client!**

---

## Resource Cleanup

When done testing, delete in this order:
1. Lambda functions: `mcp-client`, `mcp-server`, `mcp-tool-math`, `mcp-tool-string`, `mcp-tool-time`, `mcp-tool-utility`, `mcp-tool-greeting`
2. IAM roles: `mcp-client-lambda-role`, `mcp-server-lambda-role`, `mcp-tool-lambda-role`
3. IAM policies: `mcp-server-policy`, `mcp-client-policy`
4. CloudWatch log groups: `/aws/lambda/mcp-*`

---

**Next →** [06-testing-guide.md](./06-testing-guide.md) — Test questions and expected results
