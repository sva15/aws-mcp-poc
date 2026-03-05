"""
Tool Registry Lambda — Tracks all tool providers and their URLs.

This Lambda is the central catalog of all MCP tools. The MCP server
calls it via HTTP to discover what tools are available and where to
find them.

Deployed behind ALB at: /registry

Supported actions:
  - "list"       → Return all registered providers with their tools
  - "register"   → Add or update a tool provider
  - "unregister" → Remove a tool provider
  - "describe"   → Query a specific provider

Protocol:
  POST /registry {"action":"list"}
  → {"providers":[{"name":"math","url":"http://ALB/tools/math","tools":[...]}, ...]}

Architecture:
  MCP Server → HTTP POST /registry → this Lambda → returns tool catalog
  MCP Server → HTTP POST /tools/math → tool Lambda directly (NOT through registry)

The registry ONLY provides the catalog. Tool execution goes directly
to the tool's URL — the registry is NOT in the execution path.

Why Lambda (not container)?
  - Simple CRUD operations (list/register)
  - Low traffic (MCP server caches results for 5 minutes)
  - Stateless (in-memory for POC, DynamoDB for production)
  - Cost: ~$0/month

ALB Event Format:
  ALB sends events with httpMethod, path, headers, body.
  We handle both ALB events and direct invocation for testability.
"""

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─── Tool Provider Registry ─────────────────────────────────────
# In-memory storage for POC. For production, use DynamoDB or similar.
#
# Each provider entry:
#   {
#       "name": "math-tools",
#       "url": "http://tools-alb.example.com/tools/math",
#       "tools": [
#           {"name": "add", "description": "...", "input_schema": {...}},
#           ...
#       ]
#   }
#
# Pre-populated with default providers. The ALB base URL is configurable
# via environment variable so you set it once and all providers use it.

ALB_BASE_URL = os.environ.get("ALB_BASE_URL", "http://tools-alb.example.com")

# Default providers — these are loaded on cold start.
# Add new providers here or use the "register" action at runtime.
_PROVIDERS = {
    "math-tools": {
        "name": "math-tools",
        "url": f"{ALB_BASE_URL}/tools/math",
        "tools": [
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
                        "a": {"type": "number", "description": "First number"},
                        "b": {"type": "number", "description": "Second number"},
                    },
                    "required": ["a", "b"],
                },
            },
            {
                "name": "subtract",
                "description": (
                    "Subtract the second number from the first. "
                    "Use this when someone asks to subtract or find the difference."
                ),
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
                "description": (
                    "Divide the first number by the second. "
                    "Use this when someone asks to divide or find the quotient."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "Dividend"},
                        "b": {"type": "number", "description": "Divisor (cannot be zero)"},
                    },
                    "required": ["a", "b"],
                },
            },
        ],
    },
    "string-tools": {
        "name": "string-tools",
        "url": f"{ALB_BASE_URL}/tools/string",
        "tools": [
            {
                "name": "uppercase",
                "description": (
                    "Convert text to all uppercase letters. "
                    "Use when someone asks to capitalize or uppercase text."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to convert"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "reverse",
                "description": (
                    "Reverse a text string. "
                    "Use when someone asks to reverse or spell something backwards."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to reverse"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "word_count",
                "description": (
                    "Count the number of words in text. "
                    "Use when someone asks how many words are in a sentence."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to count words in"},
                    },
                    "required": ["text"],
                },
            },
        ],
    },
    "time-tools": {
        "name": "time-tools",
        "url": f"{ALB_BASE_URL}/tools/time",
        "tools": [
            {
                "name": "current_time",
                "description": (
                    "Get the current date and time in UTC. "
                    "Use when someone asks what time or date it is."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "date_diff",
                "description": (
                    "Calculate the number of days between two dates. "
                    "Use when someone asks how many days between dates."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date1": {"type": "string", "description": "First date (YYYY-MM-DD)"},
                        "date2": {"type": "string", "description": "Second date (YYYY-MM-DD)"},
                    },
                    "required": ["date1", "date2"],
                },
            },
        ],
    },
    "utility-tools": {
        "name": "utility-tools",
        "url": f"{ALB_BASE_URL}/tools/utility",
        "tools": [
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
                    "properties": {
                        "text": {"type": "string", "description": "Text to analyze"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "is_palindrome",
                "description": "Check if text is a palindrome (reads same forwards and backwards).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to check"},
                    },
                    "required": ["text"],
                },
            },
        ],
    },
}


# ─── Action Handlers ─────────────────────────────────────────────

def _handle_list() -> dict:
    """Return all registered providers with their tools."""
    providers = list(_PROVIDERS.values())
    total_tools = sum(len(p["tools"]) for p in providers)
    logger.info(f"[REGISTRY] list → {len(providers)} providers, {total_tools} tools")
    return {"providers": providers, "total_tools": total_tools}


def _handle_register(provider_data: dict) -> dict:
    """Register or update a tool provider."""
    name = provider_data.get("name")
    url = provider_data.get("url")

    if not name or not url:
        return {"error": "Provider 'name' and 'url' are required."}

    # If tools not provided, try to query the provider
    tools = provider_data.get("tools", [])

    _PROVIDERS[name] = {
        "name": name,
        "url": url,
        "tools": tools,
    }

    logger.info(f"[REGISTRY] register → '{name}' at {url} ({len(tools)} tools)")
    return {"status": "registered", "name": name, "tools_count": len(tools)}


def _handle_unregister(name: str) -> dict:
    """Remove a tool provider."""
    if name not in _PROVIDERS:
        return {"error": f"Provider '{name}' not found."}

    del _PROVIDERS[name]
    logger.info(f"[REGISTRY] unregister → '{name}' removed")
    return {"status": "unregistered", "name": name}


# ─── ALB Response Helper ─────────────────────────────────────────

def _alb_response(status_code: int, body: dict) -> dict:
    """Format response for ALB (required format for Lambda target groups)."""
    return {
        "statusCode": status_code,
        "statusDescription": f"{status_code} OK" if status_code == 200 else f"{status_code} Error",
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


# ─── Lambda Handler ──────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Entry point. Handles both ALB events and direct invocations.

    ALB event: {"httpMethod":"POST", "body":"{...}", ...}
    Direct:    {"action":"list"}
    """
    logger.info(f"[REGISTRY] Received event: {json.dumps(event)[:500]}")

    # ── Detect ALB vs Direct invocation ──────────────────────────
    is_alb = "httpMethod" in event

    if is_alb:
        # Parse body from ALB event
        body_str = event.get("body", "{}")
        try:
            body = json.loads(body_str) if body_str else {}
        except json.JSONDecodeError:
            return _alb_response(400, {"error": "Invalid JSON body"})
    else:
        # Direct invocation — the event IS the body
        body = event

    action = body.get("action", "")
    logger.info(f"[REGISTRY] Action: '{action}' (source: {'ALB' if is_alb else 'Direct'})")

    # ── Route to handler ─────────────────────────────────────────
    if action == "list":
        result = _handle_list()
    elif action == "register":
        provider_data = body.get("provider", {})
        result = _handle_register(provider_data)
    elif action == "unregister":
        name = body.get("name", "")
        result = _handle_unregister(name)
    else:
        result = {"error": f"Unknown action: '{action}'. Use 'list', 'register', or 'unregister'."}

    # ── Return in correct format ─────────────────────────────────
    if is_alb:
        status = 400 if "error" in result else 200
        return _alb_response(status, result)
    else:
        return result
