"""
String Tools Lambda Function
Provides: uppercase, reverse
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
                "name": "uppercase",
                "description": "Convert a string to uppercase",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The text to convert to uppercase"
                        }
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
                        "text": {
                            "type": "string",
                            "description": "The text to reverse"
                        }
                    },
                    "required": ["text"]
                }
            }
        ]
    }


def call_tool(tool_name: str, arguments: dict):
    """Execute the requested tool with given arguments."""
    if tool_name == "uppercase":
        text = arguments.get("text", "")
        return {"result": text.upper()}

    elif tool_name == "reverse":
        text = arguments.get("text", "")
        return {"result": text[::-1]}

    else:
        return {"error": f"Unknown tool: {tool_name}"}
