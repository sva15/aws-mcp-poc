"""
DateTime Tools Lambda Function.
Provides: current_time, date_diff

Follows the __describe__ / __call__ protocol.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)


TOOL_DEFINITIONS = [
    {
        "name": "current_time",
        "description": (
            "Get the current date and time in UTC. "
            "Use this when someone asks what time it is, what today's date is, "
            "or wants the current date and time."
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
            "Use this when someone asks how many days are between two dates, "
            "how long until a date, or the duration between events."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date1": {
                    "type": "string",
                    "description": "First date in YYYY-MM-DD format (e.g., 2026-01-15)",
                },
                "date2": {
                    "type": "string",
                    "description": "Second date in YYYY-MM-DD format (e.g., 2026-12-31)",
                },
            },
            "required": ["date1", "date2"],
        },
    },
]


def _execute_current_time() -> dict:
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
    logger.info(f"current_time() = {now.isoformat()}")
    return result


def _execute_date_diff(date1_str: str, date2_str: str) -> dict:
    try:
        d1 = datetime.strptime(date1_str, "%Y-%m-%d")
        d2 = datetime.strptime(date2_str, "%Y-%m-%d")
    except ValueError as e:
        return {"error": f"Invalid date format. Use YYYY-MM-DD. Error: {e}"}

    diff_days = abs((d2 - d1).days)
    result = {
        "result": {
            "days": diff_days,
            "weeks": round(diff_days / 7, 1),
            "months_approx": round(diff_days / 30.44, 1),
            "date1": date1_str,
            "date2": date2_str,
        }
    }
    logger.info(f"date_diff('{date1_str}', '{date2_str}') = {diff_days} days")
    return result


def lambda_handler(event, context):
    action = event.get("action", "")
    logger.info(f"[mcp-tool-time] Received action: '{action}'")

    if action == "__describe__":
        logger.info(f"[mcp-tool-time] Returning {len(TOOL_DEFINITIONS)} tool definitions")
        return {"tools": TOOL_DEFINITIONS}

    elif action == "__call__":
        tool_name = event.get("tool", "")
        arguments = event.get("arguments", {})

        logger.info(f"[mcp-tool-time] Calling tool '{tool_name}' with args: {json.dumps(arguments)}")

        if tool_name == "current_time":
            result = _execute_current_time()
        elif tool_name == "date_diff":
            date1 = arguments.get("date1", "")
            date2 = arguments.get("date2", "")
            if not date1 or not date2:
                return {"error": "Missing required parameters 'date1' and 'date2'."}
            result = _execute_date_diff(date1, date2)
        else:
            return {"error": f"Unknown tool: '{tool_name}'. Available: ['current_time', 'date_diff']"}

        logger.info(f"[mcp-tool-time] Result: {json.dumps(result)[:200]}")
        return result

    else:
        return {"error": f"Unknown action: '{action}'. Use '__describe__' or '__call__'."}
