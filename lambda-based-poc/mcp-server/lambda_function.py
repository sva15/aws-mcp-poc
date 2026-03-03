"""
MCP Server Lambda — Dynamic Tool Discovery
Automatically discovers all mcp-tool-* Lambda functions and serves their tools.
"""

import os
import json
import time
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TOOL_PREFIX = os.environ.get("TOOL_PREFIX", "mcp-tool-")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))  # 5 minutes

lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# ──────────────────────────────────────────────
# Global cache (persists between warm invocations)
# ──────────────────────────────────────────────
_tool_registry = {}
_last_discovery = 0


def discover_tools(force=False):
    """Discover all tools from Lambda functions matching the prefix."""
    global _tool_registry, _last_discovery

    if not force and _tool_registry and (time.time() - _last_discovery) < CACHE_TTL:
        logger.info(f"Using cached tool registry ({len(_tool_registry)} tools)")
        return _tool_registry

    logger.info(f"Starting tool discovery (prefix: {TOOL_PREFIX})...")
    new_registry = {}

    try:
        # List all Lambda functions (handles pagination)
        tool_lambdas = []
        paginator = lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            for func in page["Functions"]:
                if func["FunctionName"].startswith(TOOL_PREFIX):
                    tool_lambdas.append(func["FunctionName"])

        logger.info(f"Found {len(tool_lambdas)} tool Lambdas: {tool_lambdas}")

        # Query each tool Lambda for its tool definitions
        for lambda_name in tool_lambdas:
            try:
                logger.info(f"  Querying: {lambda_name}")
                response = lambda_client.invoke(
                    FunctionName=lambda_name,
                    InvocationType="RequestResponse",
                    Payload=json.dumps({"action": "__describe__"}).encode(),
                )
                payload = json.loads(response["Payload"].read().decode())

                if isinstance(payload, dict) and "body" in payload:
                    payload = (json.loads(payload["body"])
                              if isinstance(payload["body"], str)
                              else payload["body"])

                for tool_def in payload.get("tools", []):
                    tool_name = tool_def["name"]
                    new_registry[tool_name] = {
                        "lambda_name": lambda_name,
                        "description": tool_def.get("description", ""),
                        "input_schema": tool_def.get("input_schema", {}),
                    }
                    logger.info(f"    Registered: {tool_name}")

            except Exception as e:
                logger.error(f"  Failed to query {lambda_name}: {e}")

    except Exception as e:
        logger.error(f"Failed to list Lambda functions: {e}")
        if _tool_registry:
            logger.warning("Falling back to stale cache")
            return _tool_registry

    _tool_registry = new_registry
    _last_discovery = time.time()
    logger.info(f"Discovery complete: {len(_tool_registry)} tools registered")
    return _tool_registry


def invoke_tool(tool_name, arguments):
    """Invoke a specific tool on its Lambda function."""
    registry = discover_tools()

    if tool_name not in registry:
        return {"error": f"Unknown tool: {tool_name}. Available: {list(registry.keys())}"}

    tool_info = registry[tool_name]
    lambda_name = tool_info["lambda_name"]

    logger.info(f"Invoking tool '{tool_name}' on Lambda '{lambda_name}'")

    response = lambda_client.invoke(
        FunctionName=lambda_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "action": "__call__",
            "tool": tool_name,
            "arguments": arguments,
        }).encode(),
    )

    result = json.loads(response["Payload"].read().decode())

    if isinstance(result, dict) and "body" in result:
        result = (json.loads(result["body"])
                 if isinstance(result["body"], str)
                 else result["body"])

    logger.info(f"Tool '{tool_name}' returned: {result}")
    return result


# ──────────────────────────────────────────────
# JSON-RPC Handlers
# ──────────────────────────────────────────────

def handle_initialize(request_id):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-server-lambda", "version": "1.0.0"},
        },
    }


def handle_tools_list(request_id, params):
    force = params.get("force_refresh", False)
    registry = discover_tools(force=force)

    tools = []
    for name, info in registry.items():
        tools.append({
            "name": name,
            "description": info["description"],
            "inputSchema": info["input_schema"],
        })

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"tools": tools},
    }


def handle_tools_call(request_id, params):
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    result = invoke_tool(tool_name, arguments)

    if "error" in result:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": result["error"]},
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(result)}],
        },
    }


# ──────────────────────────────────────────────
# Lambda Entry Point
# ──────────────────────────────────────────────

def lambda_handler(event, context):
    """Main handler — accepts JSON-RPC requests."""
    if isinstance(event, str):
        event = json.loads(event)

    body = event
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            body = json.loads(body)

    method = body.get("method", "")
    request_id = body.get("id", 1)
    params = body.get("params", {})

    logger.info(f"MCP Server received: method={method}")

    handlers = {
        "initialize": lambda: handle_initialize(request_id),
        "notifications/initialized": lambda: {"jsonrpc": "2.0", "id": request_id, "result": {}},
        "tools/list": lambda: handle_tools_list(request_id, params),
        "tools/call": lambda: handle_tools_call(request_id, params),
    }

    handler = handlers.get(method)
    if handler:
        response = handler()
    else:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response),
    }
