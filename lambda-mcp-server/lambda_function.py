"""
MCP Server running as a Lambda Function.
Prototype for ECS vs Lambda comparison.
"""

import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_LAMBDA_ARNS = os.environ.get("TOOL_LAMBDA_ARNS", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# Global tool registry (persisted between warm invocations)
tool_registry = {}


def discover_tools():
    global tool_registry
    if tool_registry:
        return

    if not TOOL_LAMBDA_ARNS:
        return

    lambda_names = [n.strip() for n in TOOL_LAMBDA_ARNS.split(",") if n.strip()]

    for name in lambda_names:
        try:
            response = lambda_client.invoke(
                FunctionName=name,
                InvocationType="RequestResponse",
                Payload=json.dumps({"action": "__describe__"}).encode(),
            )
            payload = json.loads(response["Payload"].read().decode())
            if isinstance(payload, dict) and "body" in payload:
                payload = json.loads(payload["body"]) if isinstance(payload["body"], str) else payload["body"]

            for tool in payload.get("tools", []):
                tool_registry[tool["name"]] = {
                    "lambda_name": name,
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {}),
                }
        except Exception as e:
            logger.error(f"Failed to discover from {name}: {e}")


def lambda_handler(event, context):
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    method = body.get("method", "")
    request_id = body.get("id", 1)
    params = body.get("params", {})

    if method == "initialize":
        result = {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "aws-mcp-server-lambda", "version": "1.0.0"}
            }
        }
    elif method == "tools/list":
        discover_tools()
        tools = [{"name": n, "description": i["description"], "inputSchema": i["input_schema"]}
                 for n, i in tool_registry.items()]
        result = {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}

    elif method == "tools/call":
        discover_tools()
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name not in tool_registry:
            result = {"jsonrpc": "2.0", "id": request_id,
                      "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        else:
            info = tool_registry[tool_name]
            response = lambda_client.invoke(
                FunctionName=info["lambda_name"],
                InvocationType="RequestResponse",
                Payload=json.dumps({"action": "__call__", "tool": tool_name, "arguments": arguments}).encode(),
            )
            r = json.loads(response["Payload"].read().decode())
            if isinstance(r, dict) and "body" in r:
                r = json.loads(r["body"]) if isinstance(r["body"], str) else r["body"]
            result = {"jsonrpc": "2.0", "id": request_id,
                      "result": {"content": [{"type": "text", "text": json.dumps(r)}]}}
    else:
        result = {"jsonrpc": "2.0", "id": request_id, "result": {}}

    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(result)}
