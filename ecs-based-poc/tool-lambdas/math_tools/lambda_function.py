"""
Math Tools Lambda Function.
Provides: add, multiply, subtract, divide

Deployed behind ALB at: /tools/math
Supports both ALB events (HTTP) and direct invocation.

ALB event: {"httpMethod":"POST", "body":"{\"action\":\"__call__\",...}", ...}
Direct:    {"action":"__call__", "tool":"add", "arguments":{"a":5,"b":3}}
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ─── Tool Implementations ────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "add",
        "description": "Add two numbers together and return the sum. Use this when someone asks to add, sum, combine, or total numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number to add"},
                "b": {"type": "number", "description": "Second number to add"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "multiply",
        "description": "Multiply two numbers together and return the product. Use this when someone asks to multiply, find the product, or calculate 'X times Y'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "subtract",
        "description": "Subtract the second number from the first. Use this when someone asks to subtract or find the difference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "Number to subtract from"},
                "b": {"type": "number", "description": "Number to subtract"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "divide",
        "description": "Divide the first number by the second. Use this when someone asks to divide or find the quotient.",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "Dividend"},
                "b": {"type": "number", "description": "Divisor (cannot be zero)"},
            },
            "required": ["a", "b"],
        },
    },
]


def _execute_add(a, b):
    result = a + b
    return {"result": result, "expression": f"{a} + {b} = {result}"}

def _execute_multiply(a, b):
    result = a * b
    return {"result": result, "expression": f"{a} × {b} = {result}"}

def _execute_subtract(a, b):
    result = a - b
    return {"result": result, "expression": f"{a} - {b} = {result}"}

def _execute_divide(a, b):
    if b == 0:
        return {"error": "Cannot divide by zero."}
    result = a / b
    return {"result": result, "expression": f"{a} ÷ {b} = {result}"}


_HANDLERS = {
    "add": _execute_add,
    "multiply": _execute_multiply,
    "subtract": _execute_subtract,
    "divide": _execute_divide,
}


# ─── ALB Response Helper ─────────────────────────────────────────

def _alb_response(status_code, body):
    return {
        "statusCode": status_code,
        "statusDescription": f"{status_code} OK" if status_code == 200 else f"{status_code} Error",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


# ─── Lambda Handler ──────────────────────────────────────────────

def lambda_handler(event, context):
    """Handles both ALB events and direct invocations."""
    is_alb = "httpMethod" in event

    if is_alb:
        try:
            body = json.loads(event.get("body", "{}") or "{}")
        except json.JSONDecodeError:
            return _alb_response(400, {"error": "Invalid JSON"})
    else:
        body = event

    action = body.get("action", "")
    logger.info(f"[mcp-tool-math] action='{action}' source={'ALB' if is_alb else 'Direct'}")

    if action == "__describe__":
        result = {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = body.get("tool", "")
        arguments = body.get("arguments", {})
        handler = _HANDLERS.get(tool_name)

        if not handler:
            result = {"error": f"Unknown tool: '{tool_name}'"}
        else:
            a = arguments.get("a")
            b = arguments.get("b")
            if a is None or b is None:
                result = {"error": "Parameters 'a' and 'b' are required."}
            else:
                try:
                    result = handler(float(a), float(b))
                except (TypeError, ValueError):
                    result = {"error": f"Invalid numbers: a={a}, b={b}"}

        logger.info(f"[mcp-tool-math] {tool_name}({arguments}) → {json.dumps(result)[:200]}")
    else:
        result = {"error": f"Unknown action: '{action}'. Use '__describe__' or '__call__'."}

    return _alb_response(200, result) if is_alb else result
