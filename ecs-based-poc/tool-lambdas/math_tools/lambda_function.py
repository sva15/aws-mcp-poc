"""
Math Tools Lambda Function.
Provides: add, multiply, subtract, divide

Follows the __describe__ / __call__ protocol:
  - "__describe__" → Return tool definitions (names, descriptions, schemas)
  - "__call__"     → Execute a specific tool with given arguments

Each tool's description is written to help Bedrock understand
WHEN to use it (not just what it does). This is critical because
Bedrock reads these descriptions to decide which tool matches
the user's question.

Best Practices followed:
  - Input validation before processing
  - Clear error messages (Bedrock can use these to retry or explain)
  - Structured descriptions with usage hints
  - Complete JSON Schema definitions with types and descriptions
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ─── Tool Definitions ────────────────────────────────────────────
# These are returned by __describe__. The MCP Server registers them
# as MCP tools. The Client Lambda converts them to Bedrock format.

TOOL_DEFINITIONS = [
    {
        "name": "add",
        "description": (
            "Add two numbers together and return the sum. "
            "Use this when someone asks to add, sum, combine, or total numbers."
        ),
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
        "description": (
            "Multiply two numbers together and return the product. "
            "Use this when someone asks to multiply, find the product, "
            "or calculate 'X times Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number (multiplicand)"},
                "b": {"type": "number", "description": "Second number (multiplier)"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "subtract",
        "description": (
            "Subtract the second number from the first and return the difference. "
            "Use this when someone asks to subtract, find the difference, or 'minus'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "Number to subtract from (minuend)"},
                "b": {"type": "number", "description": "Number to subtract (subtrahend)"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "divide",
        "description": (
            "Divide the first number by the second and return the quotient. "
            "Use this when someone asks to divide, find the quotient, or 'X divided by Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "Dividend (number being divided)"},
                "b": {"type": "number", "description": "Divisor (number to divide by, cannot be zero)"},
            },
            "required": ["a", "b"],
        },
    },
]


# ─── Tool Implementations ────────────────────────────────────────

def _execute_add(a: float, b: float) -> dict:
    result = a + b
    logger.info(f"add({a}, {b}) = {result}")
    return {"result": result, "expression": f"{a} + {b} = {result}"}


def _execute_multiply(a: float, b: float) -> dict:
    result = a * b
    logger.info(f"multiply({a}, {b}) = {result}")
    return {"result": result, "expression": f"{a} × {b} = {result}"}


def _execute_subtract(a: float, b: float) -> dict:
    result = a - b
    logger.info(f"subtract({a}, {b}) = {result}")
    return {"result": result, "expression": f"{a} - {b} = {result}"}


def _execute_divide(a: float, b: float) -> dict:
    if b == 0:
        logger.warning(f"divide({a}, {b}) → Division by zero!")
        return {"error": "Cannot divide by zero. The divisor must be a non-zero number."}
    result = a / b
    logger.info(f"divide({a}, {b}) = {result}")
    return {"result": result, "expression": f"{a} ÷ {b} = {result}"}


# Map tool names to their implementation functions
_TOOL_HANDLERS = {
    "add": _execute_add,
    "multiply": _execute_multiply,
    "subtract": _execute_subtract,
    "divide": _execute_divide,
}


# ─── Lambda Handler ──────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Lambda entry point. Routes to __describe__ or __call__.

    __describe__ example:
        Input:  {"action": "__describe__"}
        Output: {"tools": [{"name": "add", "description": "...", "input_schema": {...}}, ...]}

    __call__ example:
        Input:  {"action": "__call__", "tool": "add", "arguments": {"a": 5, "b": 3}}
        Output: {"result": 8, "expression": "5 + 3 = 8"}
    """
    action = event.get("action", "")
    logger.info(f"[mcp-tool-math] Received action: '{action}'")

    if action == "__describe__":
        logger.info(f"[mcp-tool-math] Returning {len(TOOL_DEFINITIONS)} tool definitions")
        return {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = event.get("tool", "")
        arguments = event.get("arguments", {})

        logger.info(f"[mcp-tool-math] Calling tool '{tool_name}' with args: {json.dumps(arguments)}")

        handler = _TOOL_HANDLERS.get(tool_name)
        if not handler:
            error_msg = f"Unknown tool: '{tool_name}'. Available: {list(_TOOL_HANDLERS.keys())}"
            logger.error(f"[mcp-tool-math] {error_msg}")
            return {"error": error_msg}

        # Extract and validate parameters
        a = arguments.get("a")
        b = arguments.get("b")

        if a is None or b is None:
            return {"error": f"Missing required parameters. 'a' and 'b' are both required."}

        try:
            a = float(a)
            b = float(b)
        except (TypeError, ValueError) as e:
            return {"error": f"Invalid parameter types. 'a' and 'b' must be numbers. Got: a={a}, b={b}"}

        result = handler(a, b)
        logger.info(f"[mcp-tool-math] Result: {json.dumps(result)}")
        return result

    else:
        return {"error": f"Unknown action: '{action}'. Use '__describe__' or '__call__'."}
