"""
DateTime Tools Lambda Function
Provides: now, date_diff
"""

import json
from datetime import datetime, timezone


def lambda_handler(event, context):
    action = event.get("action", "")

    if action == "__describe__":
        return describe()
    elif action == "__call__":
        return call_tool(event.get("tool", ""), event.get("arguments", {}))
    else:
        return {"error": f"Unknown action: {action}"}


def describe():
    return {
        "tools": [
            {
                "name": "current_time",
                "description": "Get the current date and time in UTC. Use this when someone asks what time it is, what today's date is, or the current date and time.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "date_diff",
                "description": "Calculate the number of days between two dates. Use this when someone asks how many days are between two dates or how long until a date.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date1": {
                            "type": "string",
                            "description": "First date in YYYY-MM-DD format"
                        },
                        "date2": {
                            "type": "string",
                            "description": "Second date in YYYY-MM-DD format"
                        }
                    },
                    "required": ["date1", "date2"]
                }
            }
        ]
    }


def call_tool(tool_name, arguments):
    if tool_name == "current_time":
        now = datetime.now(timezone.utc)
        return {
            "result": {
                "datetime": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "day_of_week": now.strftime("%A"),
                "timezone": "UTC"
            }
        }

    elif tool_name == "date_diff":
        try:
            date1 = datetime.strptime(arguments.get("date1", ""), "%Y-%m-%d")
            date2 = datetime.strptime(arguments.get("date2", ""), "%Y-%m-%d")
            diff = abs((date2 - date1).days)
            return {
                "result": {
                    "days": diff,
                    "weeks": round(diff / 7, 1),
                    "months": round(diff / 30.44, 1),
                    "date1": arguments["date1"],
                    "date2": arguments["date2"]
                }
            }
        except ValueError as e:
            return {"error": f"Invalid date format. Use YYYY-MM-DD. Error: {str(e)}"}

    else:
        return {"error": f"Unknown tool: {tool_name}"}
