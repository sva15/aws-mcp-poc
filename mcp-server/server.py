"""
MCP Server for AWS ECS Fargate
Discovers tools from Lambda functions and exposes them via Streamable HTTP.
"""

import os
import json
import logging
import boto3
from mcp.server.fastmcp import FastMCP

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
TOOL_LAMBDA_ARNS = os.environ.get("TOOL_LAMBDA_ARNS", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-server")

# ──────────────────────────────────────────────
# AWS Lambda Client
# ──────────────────────────────────────────────
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# ──────────────────────────────────────────────
# Initialize MCP Server
# ──────────────────────────────────────────────
mcp = FastMCP(
    name="aws-mcp-server",
    instructions="MCP Server that delegates tool calls to AWS Lambda functions.",
)

# ──────────────────────────────────────────────
# Tool Registry
# ──────────────────────────────────────────────
# Maps tool_name -> {"lambda_name": "...", "description": "...", "input_schema": {...}}
tool_registry = {}


def discover_tools():
    """
    On startup, invoke each tool Lambda with __describe__ action
    to learn what tools they provide.
    """
    global tool_registry
    tool_registry = {}

    if not TOOL_LAMBDA_ARNS:
        logger.warning("No TOOL_LAMBDA_ARNS configured. No tools will be available.")
        return

    lambda_names = [name.strip() for name in TOOL_LAMBDA_ARNS.split(",") if name.strip()]
    logger.info(f"Discovering tools from {len(lambda_names)} Lambda functions...")

    for lambda_name in lambda_names:
        try:
            logger.info(f"  Querying: {lambda_name}")
            response = lambda_client.invoke(
                FunctionName=lambda_name,
                InvocationType="RequestResponse",
                Payload=json.dumps({"action": "__describe__"}).encode(),
            )
            payload = json.loads(response["Payload"].read().decode())

            # Handle Lambda proxy response format
            if isinstance(payload, dict) and "body" in payload:
                payload = json.loads(payload["body"]) if isinstance(payload["body"], str) else payload["body"]

            tools = payload.get("tools", [])
            for tool_def in tools:
                tool_name = tool_def["name"]
                tool_registry[tool_name] = {
                    "lambda_name": lambda_name,
                    "description": tool_def.get("description", ""),
                    "input_schema": tool_def.get("input_schema", {}),
                }
                logger.info(f"    Registered tool: {tool_name}")

        except Exception as e:
            logger.error(f"  Failed to discover tools from {lambda_name}: {e}")

    logger.info(f"Total tools discovered: {len(tool_registry)}")


def invoke_tool_lambda(lambda_name: str, tool_name: str, arguments: dict) -> dict:
    """
    Invoke a tool Lambda function with the __call__ action.
    """
    payload = {
        "action": "__call__",
        "tool": tool_name,
        "arguments": arguments,
    }

    response = lambda_client.invoke(
        FunctionName=lambda_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )

    result = json.loads(response["Payload"].read().decode())

    # Handle Lambda proxy response format
    if isinstance(result, dict) and "body" in result:
        result = json.loads(result["body"]) if isinstance(result["body"], str) else result["body"]

    return result


# ──────────────────────────────────────────────
# Dynamically Register MCP Tools
# ──────────────────────────────────────────────
def create_tool_handler(tool_name: str, lambda_name: str):
    """
    Create a closure that handles calls to a specific tool.
    """
    async def handler(**kwargs):
        logger.info(f"Calling tool '{tool_name}' on Lambda '{lambda_name}' with args: {kwargs}")
        result = invoke_tool_lambda(lambda_name, tool_name, kwargs)
        logger.info(f"Tool '{tool_name}' returned: {result}")
        return json.dumps(result)
    return handler


def register_tools():
    """
    After discovery, register each tool with the MCP server.
    """
    for tool_name, tool_info in tool_registry.items():
        handler = create_tool_handler(tool_name, tool_info["lambda_name"])
        mcp.tool(name=tool_name, description=tool_info["description"])(handler)
        logger.info(f"Registered MCP tool: {tool_name}")


# ──────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────
discover_tools()
register_tools()

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting MCP Server on port 8000...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
