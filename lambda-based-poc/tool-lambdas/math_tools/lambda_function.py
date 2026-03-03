"""
Math Tools Lambda Function
Provides: add, multiply, subtract, divide
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
                "name": "add",
                "description": "Add two numbers together and return the sum. Use this when someone asks to add, sum, or combine numbers.",
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
                "description": "Multiply two numbers together and return the product. Use this when someone asks to multiply numbers or find a product.",
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
                "name": "subtract",
                "description": "Subtract the second number from the first and return the difference. Use this when someone asks to subtract or find the difference.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "The number to subtract from"},
                        "b": {"type": "number", "description": "The number to subtract"}
                    },
                    "required": ["a", "b"]
                }
            },
            {
                "name": "divide",
                "description": "Divide the first number by the second and return the quotient. Use this when someone asks to divide numbers.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "The dividend (number being divided)"},
                        "b": {"type": "number", "description": "The divisor (number to divide by)"}
                    },
                    "required": ["a", "b"]
                }
            }
        ]
    }


def call_tool(tool_name, arguments):
    a = arguments.get("a", 0)
    b = arguments.get("b", 0)

    if tool_name == "add":
        return {"result": a + b}
    elif tool_name == "multiply":
        return {"result": a * b}
    elif tool_name == "subtract":
        return {"result": a - b}
    elif tool_name == "divide":
        if b == 0:
            return {"error": "Cannot divide by zero"}
        return {"result": a / b}
    else:
        return {"error": f"Unknown tool: {tool_name}"}
