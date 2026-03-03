"""
Utility Tools Lambda Function.
Provides: convert_temperature, calculate_percentage, generate_password,
          count_characters, is_palindrome

Demonstrates the "single Lambda, multiple tools" pattern.
One Lambda function can host ANY number of tools — they all share
the same runtime, dependencies, and IAM role.

Follows the __describe__ / __call__ protocol.
"""

import json
import logging
import random
import string

logger = logging.getLogger()
logger.setLevel(logging.INFO)


TOOL_DEFINITIONS = [
    {
        "name": "convert_temperature",
        "description": (
            "Convert temperature between Celsius and Fahrenheit. "
            "Use this when someone asks to convert temperatures between units."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "Temperature value to convert"},
                "from_unit": {
                    "type": "string",
                    "description": "Unit to convert from: 'celsius' or 'fahrenheit'",
                    "enum": ["celsius", "fahrenheit"],
                },
            },
            "required": ["value", "from_unit"],
        },
    },
    {
        "name": "calculate_percentage",
        "description": (
            "Calculate percentages. Use 'what_percent' to find what percentage A is of B, "
            "or 'percent_of' to find X% of a number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "'what_percent' to find what % A is of B, or 'percent_of' to find X% of B",
                    "enum": ["what_percent", "percent_of"],
                },
                "a": {"type": "number", "description": "First number (the part, or the percentage value)"},
                "b": {"type": "number", "description": "Second number (the whole, or the base number)"},
            },
            "required": ["operation", "a", "b"],
        },
    },
    {
        "name": "generate_password",
        "description": (
            "Generate a random secure password of a specified length. "
            "Use this when someone asks to create, generate, or make a password."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "length": {
                    "type": "integer",
                    "description": "Length of the password (8-64 characters)",
                },
                "include_special": {
                    "type": "boolean",
                    "description": "Whether to include special characters (!@#$%^&*). Default: true",
                },
            },
            "required": ["length"],
        },
    },
    {
        "name": "count_characters",
        "description": (
            "Count the number of characters in a text string. "
            "Returns counts with and without spaces, letters, and digits. "
            "Use this when someone asks how many characters or letters are in text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to count characters in"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "is_palindrome",
        "description": (
            "Check if a word or phrase is a palindrome (reads the same forwards and backwards). "
            "Ignores spaces, punctuation, and case. "
            "Use this when someone asks if something is a palindrome."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to check for palindrome"},
            },
            "required": ["text"],
        },
    },
]


# ─── Tool Implementations ────────────────────────────────────────

def _convert_temperature(value: float, from_unit: str) -> dict:
    from_unit = from_unit.lower()
    if from_unit == "celsius":
        converted = (value * 9 / 5) + 32
        return {
            "result": {
                "input": f"{value}°C",
                "output": f"{round(converted, 2)}°F",
                "value": round(converted, 2),
                "formula": f"({value} × 9/5) + 32 = {round(converted, 2)}",
            }
        }
    elif from_unit == "fahrenheit":
        converted = (value - 32) * 5 / 9
        return {
            "result": {
                "input": f"{value}°F",
                "output": f"{round(converted, 2)}°C",
                "value": round(converted, 2),
                "formula": f"({value} - 32) × 5/9 = {round(converted, 2)}",
            }
        }
    else:
        return {"error": f"Unknown unit: '{from_unit}'. Use 'celsius' or 'fahrenheit'."}


def _calculate_percentage(operation: str, a: float, b: float) -> dict:
    if operation == "what_percent":
        if b == 0:
            return {"error": "Cannot calculate percentage of zero."}
        pct = (a / b) * 100
        return {"result": {"percentage": round(pct, 2), "description": f"{a} is {round(pct, 2)}% of {b}"}}
    elif operation == "percent_of":
        val = (a / 100) * b
        return {"result": {"value": round(val, 2), "description": f"{a}% of {b} is {round(val, 2)}"}}
    else:
        return {"error": f"Unknown operation: '{operation}'. Use 'what_percent' or 'percent_of'."}


def _generate_password(length: int, include_special: bool) -> dict:
    length = min(max(length, 8), 64)  # Clamp to 8-64
    chars = string.ascii_letters + string.digits
    if include_special:
        chars += "!@#$%^&*()_+-="
    password = "".join(random.choices(chars, k=length))
    return {"result": {"password": password, "length": length, "includes_special": include_special}}


def _count_characters(text: str) -> dict:
    return {
        "result": {
            "with_spaces": len(text),
            "without_spaces": len(text.replace(" ", "")),
            "letters": sum(1 for c in text if c.isalpha()),
            "digits": sum(1 for c in text if c.isdigit()),
            "text": text,
        }
    }


def _is_palindrome(text: str) -> dict:
    cleaned = "".join(c.lower() for c in text if c.isalnum())
    is_pal = cleaned == cleaned[::-1]
    return {
        "result": {
            "is_palindrome": is_pal,
            "original": text,
            "cleaned": cleaned,
            "reversed": cleaned[::-1],
        }
    }


# ─── Lambda Handler ──────────────────────────────────────────────

def lambda_handler(event, context):
    action = event.get("action", "")
    logger.info(f"[mcp-tool-utility] Received action: '{action}'")

    if action == "__describe__":
        logger.info(f"[mcp-tool-utility] Returning {len(TOOL_DEFINITIONS)} tool definitions")
        return {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = event.get("tool", "")
        arguments = event.get("arguments", {})

        logger.info(f"[mcp-tool-utility] Calling tool '{tool_name}' with args: {json.dumps(arguments)}")

        if tool_name == "convert_temperature":
            value = arguments.get("value")
            from_unit = arguments.get("from_unit", "celsius")
            if value is None:
                return {"error": "Missing required parameter 'value'."}
            result = _convert_temperature(float(value), from_unit)

        elif tool_name == "calculate_percentage":
            operation = arguments.get("operation", "")
            a = arguments.get("a")
            b = arguments.get("b")
            if a is None or b is None:
                return {"error": "Missing required parameters 'a' and 'b'."}
            result = _calculate_percentage(operation, float(a), float(b))

        elif tool_name == "generate_password":
            length = arguments.get("length", 12)
            include_special = arguments.get("include_special", True)
            result = _generate_password(int(length), bool(include_special))

        elif tool_name == "count_characters":
            text = arguments.get("text")
            if text is None:
                return {"error": "Missing required parameter 'text'."}
            result = _count_characters(str(text))

        elif tool_name == "is_palindrome":
            text = arguments.get("text")
            if text is None:
                return {"error": "Missing required parameter 'text'."}
            result = _is_palindrome(str(text))

        else:
            available = [t["name"] for t in TOOL_DEFINITIONS]
            return {"error": f"Unknown tool: '{tool_name}'. Available: {available}"}

        logger.info(f"[mcp-tool-utility] Result: {json.dumps(result)[:200]}")
        return result

    else:
        return {"error": f"Unknown action: '{action}'. Use '__describe__' or '__call__'."}
