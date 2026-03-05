"""
String Tools Lambda Function.
Provides: uppercase, reverse, word_count

Deployed behind ALB at: /tools/string
Supports both ALB events (HTTP) and direct invocation.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


TOOL_DEFINITIONS = [
    {
        "name": "uppercase",
        "description": "Convert text to all uppercase letters. Use when someone asks to capitalize or uppercase text.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to convert"}},
            "required": ["text"],
        },
    },
    {
        "name": "reverse",
        "description": "Reverse a text string. Use when someone asks to reverse or spell something backwards.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to reverse"}},
            "required": ["text"],
        },
    },
    {
        "name": "word_count",
        "description": "Count the number of words in text. Use when someone asks how many words are in a sentence.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to count words in"}},
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
    logger.info(f"[mcp-tool-string] action='{action}' source={'ALB' if is_alb else 'Direct'}")

    if action == "__describe__":
        result = {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = body.get("tool", "")
        arguments = body.get("arguments", {})
        text = arguments.get("text")

        if text is None:
            result = {"error": "Parameter 'text' is required."}
        elif tool_name == "uppercase":
            result = {"result": str(text).upper()}
        elif tool_name == "reverse":
            result = {"result": str(text)[::-1]}
        elif tool_name == "word_count":
            words = str(text).split() if str(text).strip() else []
            result = {"result": len(words), "text": text}
        else:
            result = {"error": f"Unknown tool: '{tool_name}'"}

        logger.info(f"[mcp-tool-string] {tool_name} → {json.dumps(result)[:200]}")
    else:
        result = {"error": f"Unknown action: '{action}'."}

    return _alb_response(200, result) if is_alb else result
