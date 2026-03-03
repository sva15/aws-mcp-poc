"""
Tool Discovery Module.

Scans AWS Lambda functions by naming convention and queries each one
for its tool definitions using the __describe__ / __call__ protocol.

This module is the core of the "dynamic tool discovery" feature:
- On first call (or cache expiry), it scans ALL Lambda functions
- Filters for functions whose name starts with TOOL_PREFIX (default: "mcp-tool-")
- Invokes each with {"action": "__describe__"} to get tool definitions
- Builds a registry mapping tool_name → {lambda_name, description, input_schema}
- Returns the registry as Tool objects compatible with the MCP SDK

Why prefix-based scanning?
  - Zero configuration: deploy a new Lambda named "mcp-tool-xxx" → it's discovered
  - No env var updates, no server restarts, no config files to edit
  - The naming convention IS the registration mechanism
"""

import json
import time
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.config import AWS_REGION, TOOL_PREFIX, CACHE_TTL_SECONDS

logger = logging.getLogger("discovery")

# ─── Module-Level Cache ──────────────────────────────────────────
# These persist between requests within the same container/process.
# This is important for ECS — the container stays alive, so the cache
# survives across requests until TTL expires or container restarts.
_tool_registry: dict[str, dict[str, Any]] = {}
_last_discovery_time: float = 0.0

# AWS Lambda client — created once, reused across requests
_lambda_client = boto3.client("lambda", region_name=AWS_REGION)


def discover_tools(force: bool = False) -> dict[str, dict[str, Any]]:
    """
    Discover tools from all Lambda functions matching the prefix.

    This is the main entry point. It checks the cache first, and only
    performs a full scan when the cache is expired or force=True.

    Args:
        force: If True, bypass cache and scan immediately.

    Returns:
        Dictionary mapping tool_name → tool_info dict containing:
          - lambda_name: Name of the Lambda function hosting this tool
          - description: Human-readable description for Bedrock
          - input_schema: JSON Schema for the tool's input parameters

    How this works internally:
        1. Check if cache is still valid (within TTL)
        2. If valid, return cached registry immediately
        3. If expired (or force), call _scan_lambda_functions()
        4. For each matching Lambda, call _query_tool_lambda()
        5. Build new registry and update cache timestamp
    """
    global _tool_registry, _last_discovery_time

    # ── Cache Check ──────────────────────────────────────────────
    cache_age = time.time() - _last_discovery_time
    if not force and _tool_registry and cache_age < CACHE_TTL_SECONDS:
        logger.info(
            "CACHE HIT: Using cached tool registry "
            f"({len(_tool_registry)} tools, age: {cache_age:.0f}s / {CACHE_TTL_SECONDS}s TTL)"
        )
        return _tool_registry

    logger.info(
        f"CACHE {'EXPIRED' if _tool_registry else 'COLD START'}: "
        f"Starting full tool discovery (prefix: '{TOOL_PREFIX}')"
    )

    # ── Step 1: Find all Lambda functions matching prefix ────────
    matching_lambdas = _scan_lambda_functions()

    if not matching_lambdas:
        logger.warning(
            f"No Lambda functions found matching prefix '{TOOL_PREFIX}'. "
            "Check that tool Lambdas exist and the server has lambda:ListFunctions permission."
        )
        # Keep stale cache if available
        if _tool_registry:
            logger.warning("Keeping stale cache as fallback")
            return _tool_registry
        return {}

    # ── Step 2: Query each Lambda for its tool definitions ───────
    new_registry: dict[str, dict[str, Any]] = {}
    for lambda_name in matching_lambdas:
        tools = _query_tool_lambda(lambda_name)
        for tool_def in tools:
            tool_name = tool_def["name"]
            new_registry[tool_name] = {
                "lambda_name": lambda_name,
                "description": tool_def.get("description", f"Tool: {tool_name}"),
                "input_schema": tool_def.get("input_schema", {
                    "type": "object", "properties": {}, "required": []
                }),
            }

    # ── Step 3: Update cache ─────────────────────────────────────
    _tool_registry = new_registry
    _last_discovery_time = time.time()

    logger.info(
        f"DISCOVERY COMPLETE: {len(_tool_registry)} tools from "
        f"{len(matching_lambdas)} Lambdas → {list(_tool_registry.keys())}"
    )

    return _tool_registry


def _scan_lambda_functions() -> list[str]:
    """
    List all Lambda functions and filter by TOOL_PREFIX.

    Uses pagination to handle accounts with many Lambda functions.
    Returns a list of function names that match the prefix.

    AWS API called: lambda:ListFunctions (requires IAM permission)
    """
    matching = []

    try:
        paginator = _lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            for func in page["Functions"]:
                func_name = func["FunctionName"]
                if func_name.startswith(TOOL_PREFIX):
                    matching.append(func_name)
                    logger.debug(f"  Found tool Lambda: {func_name}")

        logger.info(f"Lambda scan: found {len(matching)} functions matching '{TOOL_PREFIX}' → {matching}")

    except ClientError as e:
        logger.error(
            f"AWS API error during Lambda scan: {e.response['Error']['Message']}. "
            "Check IAM permissions: lambda:ListFunctions is required."
        )
    except Exception as e:
        logger.error(f"Unexpected error during Lambda scan: {e}")

    return matching


def _query_tool_lambda(lambda_name: str) -> list[dict[str, Any]]:
    """
    Invoke a single tool Lambda with __describe__ to get its tool definitions.

    This sends {"action": "__describe__"} and expects back:
    {
        "tools": [
            {
                "name": "tool_name",
                "description": "What it does",
                "input_schema": { JSON Schema }
            }
        ]
    }

    Args:
        lambda_name: The AWS Lambda function name to query.

    Returns:
        List of tool definition dicts. Empty list if the Lambda fails.
    """
    try:
        logger.info(f"  Querying {lambda_name} with __describe__...")

        response = _lambda_client.invoke(
            FunctionName=lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"action": "__describe__"}).encode("utf-8"),
        )

        # Parse the response payload
        payload_bytes = response["Payload"].read()
        payload = json.loads(payload_bytes.decode("utf-8"))

        # Handle Lambda responses that wrap in statusCode/body
        if isinstance(payload, dict) and "body" in payload:
            body = payload["body"]
            payload = json.loads(body) if isinstance(body, str) else body

        tools = payload.get("tools", [])
        tool_names = [t["name"] for t in tools]
        logger.info(f"    ✓ {lambda_name}: {len(tools)} tools → {tool_names}")

        return tools

    except ClientError as e:
        logger.error(f"    ✗ AWS error querying {lambda_name}: {e.response['Error']['Message']}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"    ✗ Invalid JSON from {lambda_name}: {e}")
        return []
    except Exception as e:
        logger.error(f"    ✗ Unexpected error querying {lambda_name}: {e}")
        return []


def invoke_tool(tool_name: str, arguments: dict) -> dict[str, Any]:
    """
    Invoke a specific tool on its hosting Lambda function.

    This is called when a client sends tools/call. It looks up which
    Lambda hosts the requested tool, then invokes it with __call__.

    Args:
        tool_name: Name of the tool to invoke (e.g., "add", "multiply")
        arguments: Tool arguments (e.g., {"a": 15, "b": 27})

    Returns:
        The tool's result dict. Contains either {"result": ...} or {"error": ...}

    Raises:
        ValueError: If the tool name is not in the registry.
    """
    registry = discover_tools()  # Uses cache automatically

    if tool_name not in registry:
        available = list(registry.keys())
        logger.error(f"TOOL NOT FOUND: '{tool_name}'. Available tools: {available}")
        raise ValueError(
            f"Unknown tool: '{tool_name}'. Available tools: {available}"
        )

    tool_info = registry[tool_name]
    lambda_name = tool_info["lambda_name"]

    logger.info(
        f"INVOKE TOOL: '{tool_name}' → Lambda '{lambda_name}' "
        f"with arguments: {json.dumps(arguments)}"
    )

    try:
        response = _lambda_client.invoke(
            FunctionName=lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "action": "__call__",
                "tool": tool_name,
                "arguments": arguments,
            }).encode("utf-8"),
        )

        payload_bytes = response["Payload"].read()
        result = json.loads(payload_bytes.decode("utf-8"))

        # Handle wrapped responses
        if isinstance(result, dict) and "body" in result:
            body = result["body"]
            result = json.loads(body) if isinstance(body, str) else body

        logger.info(f"TOOL RESULT: '{tool_name}' → {json.dumps(result)[:200]}")
        return result

    except ClientError as e:
        error_msg = f"AWS error invoking {lambda_name}: {e.response['Error']['Message']}"
        logger.error(f"TOOL ERROR: {error_msg}")
        return {"error": error_msg}
    except Exception as e:
        error_msg = f"Error invoking tool '{tool_name}': {str(e)}"
        logger.error(f"TOOL ERROR: {error_msg}")
        return {"error": error_msg}
