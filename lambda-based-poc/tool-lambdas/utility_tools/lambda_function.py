"""
Utility Tools Lambda Function — Multiple Diverse Tools in ONE Lambda
Provides: convert_temperature, calculate_percentage, generate_password, 
          count_characters, is_palindrome
"""

import json
import random
import string


def lambda_handler(event, context):
    action = event.get("action", "")

    if action == "__describe__":
        return describe()
    elif action == "__call__":
        return call_tool(event.get("tool", ""), event.get("arguments", {}))
    else:
        return {"error": f"Unknown action: {action}"}


def describe():
    """Return definitions for ALL 5 tools in this single Lambda."""
    return {
        "tools": [
            {
                "name": "convert_temperature",
                "description": "Convert temperature between Celsius and Fahrenheit. Use this when someone asks to convert temperatures.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number", "description": "The temperature value to convert"},
                        "from_unit": {
                            "type": "string",
                            "description": "The unit to convert from: 'celsius' or 'fahrenheit'",
                            "enum": ["celsius", "fahrenheit"]
                        }
                    },
                    "required": ["value", "from_unit"]
                }
            },
            {
                "name": "calculate_percentage",
                "description": "Calculate what percentage one number is of another, or find a percentage of a number. Use this when someone asks about percentages.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "description": "'what_percent' to find what % A is of B, or 'percent_of' to find X% of a number",
                            "enum": ["what_percent", "percent_of"]
                        },
                        "a": {"type": "number", "description": "First number (the part, or the percentage)"},
                        "b": {"type": "number", "description": "Second number (the whole, or the base number)"}
                    },
                    "required": ["operation", "a", "b"]
                }
            },
            {
                "name": "generate_password",
                "description": "Generate a random secure password of a given length. Use this when someone asks to create or generate a password.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "length": {
                            "type": "integer",
                            "description": "Length of the password (8-64 characters)"
                        },
                        "include_special": {
                            "type": "boolean",
                            "description": "Whether to include special characters like !@#$%"
                        }
                    },
                    "required": ["length"]
                }
            },
            {
                "name": "count_characters",
                "description": "Count the number of characters in a text string, with and without spaces. Use this when someone asks how many characters or letters are in a text.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to count characters in"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "is_palindrome",
                "description": "Check if a word or phrase is a palindrome (reads the same forwards and backwards). Use this when someone asks if something is a palindrome.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to check"}
                    },
                    "required": ["text"]
                }
            }
        ]
    }


def call_tool(tool_name, arguments):
    """Route to the correct tool implementation."""

    if tool_name == "convert_temperature":
        value = arguments.get("value", 0)
        from_unit = arguments.get("from_unit", "celsius").lower()

        if from_unit == "celsius":
            converted = (value * 9 / 5) + 32
            return {
                "result": {
                    "input": f"{value}°C",
                    "output": f"{round(converted, 2)}°F",
                    "value": round(converted, 2),
                    "formula": f"({value} × 9/5) + 32 = {round(converted, 2)}"
                }
            }
        elif from_unit == "fahrenheit":
            converted = (value - 32) * 5 / 9
            return {
                "result": {
                    "input": f"{value}°F",
                    "output": f"{round(converted, 2)}°C",
                    "value": round(converted, 2),
                    "formula": f"({value} - 32) × 5/9 = {round(converted, 2)}"
                }
            }
        else:
            return {"error": f"Unknown unit: {from_unit}. Use 'celsius' or 'fahrenheit'"}

    elif tool_name == "calculate_percentage":
        operation = arguments.get("operation", "what_percent")
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)

        if operation == "what_percent":
            if b == 0:
                return {"error": "Cannot calculate percentage of zero"}
            percentage = (a / b) * 100
            return {
                "result": {
                    "percentage": round(percentage, 2),
                    "description": f"{a} is {round(percentage, 2)}% of {b}"
                }
            }
        elif operation == "percent_of":
            result = (a / 100) * b
            return {
                "result": {
                    "value": round(result, 2),
                    "description": f"{a}% of {b} is {round(result, 2)}"
                }
            }
        else:
            return {"error": f"Unknown operation: {operation}"}

    elif tool_name == "generate_password":
        length = min(max(arguments.get("length", 12), 8), 64)
        include_special = arguments.get("include_special", True)

        chars = string.ascii_letters + string.digits
        if include_special:
            chars += "!@#$%^&*()_+-="

        password = "".join(random.choices(chars, k=length))
        return {
            "result": {
                "password": password,
                "length": length,
                "includes_special_characters": include_special
            }
        }

    elif tool_name == "count_characters":
        text = arguments.get("text", "")
        return {
            "result": {
                "with_spaces": len(text),
                "without_spaces": len(text.replace(" ", "")),
                "letters_only": sum(1 for c in text if c.isalpha()),
                "digits_only": sum(1 for c in text if c.isdigit()),
                "text": text
            }
        }

    elif tool_name == "is_palindrome":
        text = arguments.get("text", "")
        cleaned = "".join(c.lower() for c in text if c.isalnum())
        is_pal = cleaned == cleaned[::-1]
        return {
            "result": {
                "is_palindrome": is_pal,
                "original": text,
                "cleaned": cleaned,
                "reversed": cleaned[::-1]
            }
        }

    else:
        return {"error": f"Unknown tool: {tool_name}"}
