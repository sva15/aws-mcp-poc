"""
Math Tools Lambda Function
Provides: add, multiply
Each tool Lambda follows the __describe__ / __call__ protocol.
"""

import json


def lambda_handler(event, context):
    """
    Entry point for the Lambda function.
    Handles two actions:
      - __describe__: Return tool definitions
      - __call__: Execute a specific tool
    """
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
    """Return tool definitions for this Lambda."""
    return {
        "tools": [
            {
                "name": "add",
                "description": "Add two numbers together and return the sum",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {
                            "type": "number",
                            "description": "First number"
                        },
                        "b": {
                            "type": "number",
                            "description": "Second number"
                        }
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
                        "a": {
                            "type": "number",
                            "description": "First number"
                        },
                        "b": {
                            "type": "number",
                            "description": "Second number"
                        }
                    },
                    "required": ["a", "b"]
                }
            }
        ]
    }


def call_tool(tool_name: str, arguments: dict):
    """Execute the requested tool with given arguments."""
    if tool_name == "add":
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        result = a + b
        return {"result": result}

    elif tool_name == "multiply":
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        result = a * b
        return {"result": result}

    else:
        return {"error": f"Unknown tool: {tool_name}"}
