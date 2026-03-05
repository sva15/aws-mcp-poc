"""
DateTime Tools Lambda Function.
Provides: current_time, date_diff

Deployed behind ALB at: /tools/time
Supports both ALB events (HTTP) and direct invocation.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)


TOOL_DEFINITIONS = [
    {
        "name": "current_time",
        "description": "Get the current date and time in UTC. Use when someone asks what time or date it is.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "date_diff",
        "description": "Calculate the number of days between two dates. Use when someone asks how many days between dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date1": {"type": "string", "description": "First date (YYYY-MM-DD)"},
                "date2": {"type": "string", "description": "Second date (YYYY-MM-DD)"},
            },
            "required": ["date1", "date2"],
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
    logger.info(f"[mcp-tool-time] action='{action}' source={'ALB' if is_alb else 'Direct'}")

    if action == "__describe__":
        result = {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = body.get("tool", "")
        arguments = body.get("arguments", {})

        if tool_name == "current_time":
            now = datetime.now(timezone.utc)
            result = {
                "result": {
                    "iso": now.isoformat(),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                    "day_of_week": now.strftime("%A"),
                    "timezone": "UTC",
                }
            }
        elif tool_name == "date_diff":
            d1_str = arguments.get("date1", "")
            d2_str = arguments.get("date2", "")
            if not d1_str or not d2_str:
                result = {"error": "Parameters 'date1' and 'date2' are required."}
            else:
                try:
                    d1 = datetime.strptime(d1_str, "%Y-%m-%d")
                    d2 = datetime.strptime(d2_str, "%Y-%m-%d")
                    diff = abs((d2 - d1).days)
                    result = {"result": {"days": diff, "weeks": round(diff / 7, 1), "date1": d1_str, "date2": d2_str}}
                except ValueError as e:
                    result = {"error": f"Invalid date format. Use YYYY-MM-DD. {e}"}
        else:
            result = {"error": f"Unknown tool: '{tool_name}'"}

        logger.info(f"[mcp-tool-time] {tool_name} → {json.dumps(result)[:200]}")
    else:
        result = {"error": f"Unknown action: '{action}'."}

    return _alb_response(200, result) if is_alb else result
