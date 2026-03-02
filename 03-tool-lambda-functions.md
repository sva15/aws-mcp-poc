# Tool Lambda Functions — Code & Setup

This document covers the two tool Lambda functions that provide tools to the MCP server.

---

## How Tool Lambdas Work

Each tool Lambda follows a simple **describe/call protocol**:

```
┌────────────────────┐                    ┌──────────────────┐
│   MCP Server       │  __describe__      │  Tool Lambda     │
│   (ECS Fargate)    │───────────────────▶│  (e.g. math)     │
│                    │◀───────────────────│                  │
│                    │  {tools: [...]}    │                  │
│                    │                    │                  │
│                    │  __call__          │                  │
│                    │  tool: "add"       │                  │
│                    │  args: {a:5, b:3}  │                  │
│                    │───────────────────▶│                  │
│                    │◀───────────────────│                  │
│                    │  {result: 8}       │                  │
└────────────────────┘                    └──────────────────┘
```

---

## Lambda 1: Math Tools (`mcp-tool-math`)

### File: `tool-lambdas/math_tools/lambda_function.py`

```python
"""
Math Tools Lambda Function
Provides: add, multiply
"""

import json


def lambda_handler(event, context):
    action = event.get("action", "")

    if action == "__describe__":
        return describe()
    elif action == "__call__":
        return call_tool(event.get("tool", ""), event.get("arguments", {}))
    else:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Unknown action: {action}"})
        }


def describe():
    return {
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
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First number"},
                        "b": {"type": "number", "description": "Second number"}
                    },
                    "required": ["a", "b"]
                }
            }
        ]
    }


def call_tool(tool_name: str, arguments: dict):
    if tool_name == "add":
        return {"result": arguments.get("a", 0) + arguments.get("b", 0)}
    elif tool_name == "multiply":
        return {"result": arguments.get("a", 0) * arguments.get("b", 0)}
    else:
        return {"error": f"Unknown tool: {tool_name}"}
```

### Tools Provided

| Tool | Description | Input | Output |
|------|-------------|-------|--------|
| `add` | Add two numbers | `{"a": 5, "b": 3}` | `{"result": 8}` |
| `multiply` | Multiply two numbers | `{"a": 7, "b": 6}` | `{"result": 42}` |

### Test Locally

You can test this Lambda locally before deploying:

```python
# Save as test_math.py and run: python test_math.py
import sys
sys.path.insert(0, 'tool-lambdas/math_tools')
from lambda_function import lambda_handler

# Test describe
print("=== Describe ===")
print(lambda_handler({"action": "__describe__"}, None))

# Test add
print("\n=== Add 5 + 3 ===")
print(lambda_handler({"action": "__call__", "tool": "add", "arguments": {"a": 5, "b": 3}}, None))

# Test multiply
print("\n=== Multiply 7 x 6 ===")
print(lambda_handler({"action": "__call__", "tool": "multiply", "arguments": {"a": 7, "b": 6}}, None))
```

---

## Lambda 2: String Tools (`mcp-tool-string`)

### File: `tool-lambdas/string_tools/lambda_function.py`

```python
"""
String Tools Lambda Function
Provides: uppercase, reverse
"""

import json


def lambda_handler(event, context):
    action = event.get("action", "")

    if action == "__describe__":
        return describe()
    elif action == "__call__":
        return call_tool(event.get("tool", ""), event.get("arguments", {}))
    else:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Unknown action: {action}"})
        }


def describe():
    return {
        "tools": [
            {
                "name": "uppercase",
                "description": "Convert a string to uppercase",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to convert"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "reverse",
                "description": "Reverse a string",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to reverse"}
                    },
                    "required": ["text"]
                }
            }
        ]
    }


def call_tool(tool_name: str, arguments: dict):
    if tool_name == "uppercase":
        return {"result": arguments.get("text", "").upper()}
    elif tool_name == "reverse":
        return {"result": arguments.get("text", "")[::-1]}
    else:
        return {"error": f"Unknown tool: {tool_name}"}
```

### Tools Provided

| Tool | Description | Input | Output |
|------|-------------|-------|--------|
| `uppercase` | Convert text to uppercase | `{"text": "hello"}` | `{"result": "HELLO"}` |
| `reverse` | Reverse a string | `{"text": "aws"}` | `{"result": "swa"}` |

---

## Adding New Tool Lambdas (Extensibility)

Want to add more tools? Create a new Lambda following this template:

```python
def lambda_handler(event, context):
    action = event.get("action", "")
    if action == "__describe__":
        return {
            "tools": [
                {
                    "name": "your_tool_name",
                    "description": "What this tool does",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "param1": {"type": "string", "description": "..."}
                        },
                        "required": ["param1"]
                    }
                }
            ]
        }
    elif action == "__call__":
        tool = event.get("tool")
        args = event.get("arguments", {})
        # Your tool logic here
        return {"result": "..."}
```

Then:
1. Deploy the new Lambda
2. Add its name to the `TOOL_LAMBDA_ARNS` environment variable on the ECS task
3. Restart the ECS service — the MCP server will auto-discover the new tools

---

**Next:** Go to [04-client-lambda-code.md](./04-client-lambda-code.md) for the client Lambda implementation.
