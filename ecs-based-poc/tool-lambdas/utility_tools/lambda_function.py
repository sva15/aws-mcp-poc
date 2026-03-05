"""
Utility Tools Lambda Function.
Provides: convert_temperature, calculate_percentage, generate_password,
          count_characters, is_palindrome

Deployed behind ALB at: /tools/utility
Demonstrates a single Lambda hosting multiple tools.
Supports both ALB events (HTTP) and direct invocation.
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
        "description": "Convert temperature between Celsius and Fahrenheit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "Temperature value"},
                "from_unit": {"type": "string", "description": "'celsius' or 'fahrenheit'", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["value", "from_unit"],
        },
    },
    {
        "name": "calculate_percentage",
        "description": "Calculate percentages. 'what_percent': A is what % of B. 'percent_of': X% of B.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["what_percent", "percent_of"]},
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["operation", "a", "b"],
        },
    },
    {
        "name": "generate_password",
        "description": "Generate a random secure password.",
        "input_schema": {
            "type": "object",
            "properties": {
                "length": {"type": "integer", "description": "Password length (8-64)"},
                "include_special": {"type": "boolean", "description": "Include special chars"},
            },
            "required": ["length"],
        },
    },
    {
        "name": "count_characters",
        "description": "Count characters, letters, and digits in text.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to analyze"}},
            "required": ["text"],
        },
    },
    {
        "name": "is_palindrome",
        "description": "Check if text is a palindrome (reads same forwards and backwards).",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to check"}},
            "required": ["text"],
        },
    },
]


def _alb_response(status_code, body):
    return {
        "statusCode": status_code,
        "statusDescription": f"{status_code} OK" if status_code == 200 else f"{status_code} Error",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def lambda_handler(event, context):
    is_alb = "httpMethod" in event

    if is_alb:
        try:
            body = json.loads(event.get("body", "{}") or "{}")
        except json.JSONDecodeError:
            return _alb_response(400, {"error": "Invalid JSON"})
    else:
        body = event

    action = body.get("action", "")
    logger.info(f"[mcp-tool-utility] action='{action}' source={'ALB' if is_alb else 'Direct'}")

    if action == "__describe__":
        result = {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = body.get("tool", "")
        arguments = body.get("arguments", {})

        if tool_name == "convert_temperature":
            value = float(arguments.get("value", 0))
            from_unit = arguments.get("from_unit", "celsius").lower()
            if from_unit == "celsius":
                converted = (value * 9 / 5) + 32
                result = {"result": {"input": f"{value}°C", "output": f"{round(converted, 2)}°F", "value": round(converted, 2)}}
            elif from_unit == "fahrenheit":
                converted = (value - 32) * 5 / 9
                result = {"result": {"input": f"{value}°F", "output": f"{round(converted, 2)}°C", "value": round(converted, 2)}}
            else:
                result = {"error": f"Unknown unit: '{from_unit}'. Use 'celsius' or 'fahrenheit'."}

        elif tool_name == "calculate_percentage":
            op = arguments.get("operation", "")
            a = float(arguments.get("a", 0))
            b = float(arguments.get("b", 0))
            if op == "what_percent":
                pct = (a / b) * 100 if b != 0 else 0
                result = {"result": {"percentage": round(pct, 2), "description": f"{a} is {round(pct, 2)}% of {b}"}}
            elif op == "percent_of":
                val = (a / 100) * b
                result = {"result": {"value": round(val, 2), "description": f"{a}% of {b} is {round(val, 2)}"}}
            else:
                result = {"error": f"Unknown operation: '{op}'."}

        elif tool_name == "generate_password":
            length = min(max(int(arguments.get("length", 12)), 8), 64)
            include_special = arguments.get("include_special", True)
            chars = string.ascii_letters + string.digits
            if include_special:
                chars += "!@#$%^&*()_+-="
            password = "".join(random.choices(chars, k=length))
            result = {"result": {"password": password, "length": length}}

        elif tool_name == "count_characters":
            text = str(arguments.get("text", ""))
            result = {"result": {"with_spaces": len(text), "without_spaces": len(text.replace(" ", "")), "letters": sum(1 for c in text if c.isalpha()), "digits": sum(1 for c in text if c.isdigit())}}

        elif tool_name == "is_palindrome":
            text = str(arguments.get("text", ""))
            cleaned = "".join(c.lower() for c in text if c.isalnum())
            is_pal = cleaned == cleaned[::-1]
            result = {"result": {"is_palindrome": is_pal, "original": text, "cleaned": cleaned}}

        else:
            result = {"error": f"Unknown tool: '{tool_name}'"}

        logger.info(f"[mcp-tool-utility] {tool_name} → {json.dumps(result)[:200]}")
    else:
        result = {"error": f"Unknown action: '{action}'."}

    return _alb_response(200, result) if is_alb else result
