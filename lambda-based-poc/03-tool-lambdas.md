# Tool Lambda Functions — Code & How to Add New Tools

---

## Tool Lambda Protocol

Every tool Lambda follows a simple 2-action contract:

```python
def lambda_handler(event, context):
    action = event.get("action", "")
    
    if action == "__describe__":
        # Return: list of tool definitions (name, description, schema)
        return {"tools": [...]}
    
    elif action == "__call__":
        # Execute the requested tool
        tool = event.get("tool", "")
        args = event.get("arguments", {})
        return {"result": ...}
```

### `__describe__` Response Format

```json
{
    "tools": [
        {
            "name": "tool_name",
            "description": "Clear description of what this tool does. Include WHEN to use it.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "What this parameter is"}
                },
                "required": ["param1"]
            }
        }
    ]
}
```

> **Important:** The `description` field is critical! Bedrock reads it to decide when to use the tool. Write descriptions that clearly explain **when** the tool should be used, not just what it does.

### `__call__` Response Format

```json
{"result": 42}
```
or for errors:
```json
{"error": "Cannot divide by zero"}
```

---

## POC Tool Lambdas

### Tool Lambda 1: `mcp-tool-math` (4 tools)

| Tool | Description | Example |
|------|-------------|---------|
| `add` | Add two numbers | `add(15, 27)` → `42` |
| `multiply` | Multiply two numbers | `multiply(7, 6)` → `42` |
| `subtract` | Subtract b from a | `subtract(100, 58)` → `42` |
| `divide` | Divide a by b | `divide(84, 2)` → `42` |

**Source:** `tool-lambdas/math_tools/lambda_function.py`

### Tool Lambda 2: `mcp-tool-string` (3 tools)

| Tool | Description | Example |
|------|-------------|---------|
| `uppercase` | Convert text to uppercase | `uppercase("hello")` → `"HELLO"` |
| `reverse` | Reverse a string | `reverse("hello")` → `"olleh"` |
| `word_count` | Count words in text | `word_count("hello world")` → `2` |

**Source:** `tool-lambdas/string_tools/lambda_function.py`

### Tool Lambda 3: `mcp-tool-time` (2 tools)

| Tool | Description | Example |
|------|-------------|---------|
| `current_time` | Get current UTC date/time | → `"2026-03-03T09:30:00+00:00"` |
| `date_diff` | Days between two dates | `date_diff("2026-01-01", "2026-12-31")` → `364 days` |

**Source:** `tool-lambdas/datetime_tools/lambda_function.py`

---

## How to Add a New Tool Lambda (Step by Step)

### Example: Adding a Weather Tools Lambda

**Step 1: Write the code**

```python
# lambda_function.py for mcp-tool-weather

import json

def lambda_handler(event, context):
    action = event.get("action", "")
    if action == "__describe__":
        return describe()
    elif action == "__call__":
        return call_tool(event.get("tool", ""), event.get("arguments", {}))
    else:
        return {"error": f"Unknown action: {action}"}


def describe():
    return {
        "tools": [
            {
                "name": "get_weather",
                "description": "Get the current weather for a city. Use this when someone asks about the weather in a specific location.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name, e.g. London"}
                    },
                    "required": ["city"]
                }
            }
        ]
    }


def call_tool(tool_name, arguments):
    if tool_name == "get_weather":
        city = arguments.get("city", "Unknown")
        # In a real implementation, call a weather API
        return {
            "result": {
                "city": city,
                "temperature": "22°C",
                "condition": "Sunny",
                "humidity": "45%"
            }
        }
    return {"error": f"Unknown tool: {tool_name}"}
```

**Step 2: Deploy to AWS Lambda**

1. Go to **Lambda Console** → **Create Function**
2. **Name**: `mcp-tool-weather` (MUST start with `mcp-tool-`)
3. **Runtime**: Python 3.12
4. Paste the code → **Deploy**

**Step 3: Test it**

```json
{"action": "__describe__"}
```
→ Should return tool definitions

```json
{"action": "__call__", "tool": "get_weather", "arguments": {"city": "London"}}
```
→ Should return weather data

**Step 4: Verify Discovery**

Go to the Client Lambda and run:
```json
{"action": "list_tools"}
```
→ Should now include `get_weather` in the list

**Step 5: Test with a Question**

```json
{"question": "What is the weather in London?"}
```
→ Bedrock will call `get_weather` and give you the answer

**That's it!** No changes needed to the MCP server or client. The new tool is automatically discovered.

---

## Naming Convention Rules

| Rule | Example | Valid? |
|------|---------|--------|
| Must start with `mcp-tool-` | `mcp-tool-weather` | ✅ |
| Can have any suffix | `mcp-tool-database-queries` | ✅ |
| Cannot omit prefix | `weather-tool` | ❌ Not discovered |
| Case sensitive | `MCP-Tool-weather` | ❌ Not discovered |

---

## Tool Description Best Practices

Bedrock uses the tool description to decide when to call it. Better descriptions = better AI decisions.

| ❌ Bad Description | ✅ Good Description |
|-------------------|---------------------|
| "Add numbers" | "Add two numbers together and return the sum. Use this when someone asks to add, sum, or combine numbers." |
| "Reverse" | "Reverse a string so the last character becomes first. Use this when someone asks to reverse text or spell something backwards." |
| "Time" | "Get the current date and time in UTC. Use this when someone asks what time it is, what today's date is, or the current date and time." |

---

**Next →** [04-client-lambda.md](./04-client-lambda.md) — How Bedrock decides which tool to call
