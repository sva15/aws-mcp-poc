"""
String Tools Lambda Function
Provides: uppercase, reverse, word_count
"""

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
                "name": "uppercase",
                "description": "Convert a string to all uppercase letters. Use this when someone asks to capitalize or uppercase text.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to convert to uppercase"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "reverse",
                "description": "Reverse a string so the last character becomes first. Use this when someone asks to reverse text or spell something backwards.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to reverse"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "word_count",
                "description": "Count the number of words in a text string. Use this when someone asks how many words are in a sentence or text.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to count words in"}
                    },
                    "required": ["text"]
                }
            }
        ]
    }


def call_tool(tool_name, arguments):
    text = arguments.get("text", "")

    if tool_name == "uppercase":
        return {"result": text.upper()}
    elif tool_name == "reverse":
        return {"result": text[::-1]}
    elif tool_name == "word_count":
        count = len(text.split()) if text.strip() else 0
        return {"result": count, "text": text}
    else:
        return {"error": f"Unknown tool: {tool_name}"}
