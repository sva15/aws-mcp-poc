"""
String Tools Lambda Function.
Provides: uppercase, reverse, word_count

Follows the __describe__ / __call__ protocol.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


TOOL_DEFINITIONS = [
    {
        "name": "uppercase",
        "description": (
            "Convert a text string to all uppercase letters. "
            "Use this when someone asks to capitalize, uppercase, or make text all caps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to convert to uppercase"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "reverse",
        "description": (
            "Reverse a text string so the last character becomes the first. "
            "Use this when someone asks to reverse text, spell something backwards, "
            "or flip a string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to reverse"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "word_count",
        "description": (
            "Count the number of words in a text string. "
            "Use this when someone asks how many words are in a sentence or text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to count words in"},
            },
            "required": ["text"],
        },
    },
]


def _execute_uppercase(text: str) -> dict:
    result = text.upper()
    logger.info(f"uppercase('{text[:50]}') = '{result[:50]}'")
    return {"result": result}


def _execute_reverse(text: str) -> dict:
    result = text[::-1]
    logger.info(f"reverse('{text[:50]}') = '{result[:50]}'")
    return {"result": result}


def _execute_word_count(text: str) -> dict:
    words = text.split() if text.strip() else []
    count = len(words)
    logger.info(f"word_count('{text[:50]}') = {count}")
    return {"result": count, "text": text}


_TOOL_HANDLERS = {
    "uppercase": _execute_uppercase,
    "reverse": _execute_reverse,
    "word_count": _execute_word_count,
}


def lambda_handler(event, context):
    action = event.get("action", "")
    logger.info(f"[mcp-tool-string] Received action: '{action}'")

    if action == "__describe__":
        logger.info(f"[mcp-tool-string] Returning {len(TOOL_DEFINITIONS)} tool definitions")
        return {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = event.get("tool", "")
        arguments = event.get("arguments", {})

        logger.info(f"[mcp-tool-string] Calling tool '{tool_name}' with args: {json.dumps(arguments)}")

        handler = _TOOL_HANDLERS.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: '{tool_name}'. Available: {list(_TOOL_HANDLERS.keys())}"}

        text = arguments.get("text")
        if text is None:
            return {"error": "Missing required parameter 'text'."}

        text = str(text)
        result = handler(text)
        logger.info(f"[mcp-tool-string] Result: {json.dumps(result)[:200]}")
        return result

    else:
        return {"error": f"Unknown action: '{action}'. Use '__describe__' or '__call__'."}
