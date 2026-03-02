"""
MCP Client Lambda Function
Connects to MCP Server on ECS Fargate via HTTP.
Discovers tools and invokes them.
"""

import os
import json
import logging
from urllib import request, error

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000")
MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-client")


def send_mcp_request(method: str, params: dict = None) -> dict:
    """
    Send a JSON-RPC request to the MCP server.
    Uses only stdlib (no external dependencies needed).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    req = request.Request(MCP_ENDPOINT, data=data, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")

            # Handle SSE responses (text/event-stream)
            if "text/event-stream" in content_type:
                return parse_sse_response(response_body)

            # Handle direct JSON response
            return json.loads(response_body)

    except error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def parse_sse_response(body: str) -> dict:
    """Parse Server-Sent Events response to extract the JSON-RPC result."""
    last_data = None
    for line in body.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            last_data = line[6:]

    if last_data:
        try:
            return json.loads(last_data)
        except json.JSONDecodeError:
            return {"raw_data": last_data}

    return {"error": "No data in SSE response"}


def lambda_handler(event, context):
    """
    Lambda entry point.

    Supports these test actions:
    - "list_tools": Discover all available tools
    - "call_tool": Call a specific tool with arguments
    - "full_test": List tools + call each one

    Example event:
    {
        "action": "list_tools"
    }
    or
    {
        "action": "call_tool",
        "tool_name": "add",
        "arguments": {"a": 5, "b": 3}
    }
    or
    {
        "action": "full_test"
    }
    """
    action = event.get("action", "full_test")
    results = {}

    logger.info(f"MCP Client Lambda invoked with action: {action}")
    logger.info(f"MCP Server URL: {MCP_SERVER_URL}")

    # ── Step 1: Initialize connection ──
    logger.info("Step 1: Initializing MCP connection...")
    init_response = send_mcp_request("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {
            "name": "aws-lambda-mcp-client",
            "version": "1.0.0"
        }
    })
    results["initialize"] = init_response
    logger.info(f"Init response: {json.dumps(init_response, indent=2)}")

    if action in ("list_tools", "full_test"):
        # ── Step 2: List tools ──
        logger.info("Step 2: Listing available tools...")
        tools_response = send_mcp_request("tools/list")
        results["tools_list"] = tools_response
        logger.info(f"Tools response: {json.dumps(tools_response, indent=2)}")

    if action == "call_tool":
        # ── Call a specific tool ──
        tool_name = event.get("tool_name", "add")
        arguments = event.get("arguments", {"a": 5, "b": 3})
        logger.info(f"Calling tool: {tool_name} with args: {arguments}")

        call_response = send_mcp_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        results["tool_call"] = {
            "tool": tool_name,
            "arguments": arguments,
            "response": call_response,
        }

    elif action == "full_test":
        # ── Step 3: Call each tool with test data ──
        test_calls = [
            {"tool": "add", "arguments": {"a": 10, "b": 20}},
            {"tool": "multiply", "arguments": {"a": 7, "b": 6}},
            {"tool": "uppercase", "arguments": {"text": "hello mcp"}},
            {"tool": "reverse", "arguments": {"text": "aws lambda"}},
        ]

        results["tool_calls"] = []
        for test in test_calls:
            logger.info(f"Step 3: Calling tool '{test['tool']}'...")
            call_response = send_mcp_request("tools/call", {
                "name": test["tool"],
                "arguments": test["arguments"],
            })
            result_entry = {
                "tool": test["tool"],
                "arguments": test["arguments"],
                "response": call_response,
            }
            results["tool_calls"].append(result_entry)
            logger.info(f"  Result: {json.dumps(call_response, indent=2)}")

    return {
        "statusCode": 200,
        "body": json.dumps(results, indent=2, default=str)
    }
