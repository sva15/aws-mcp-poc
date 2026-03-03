"""
MCP Server — Uses the official MCP Python SDK's low-level Server API.

Why low-level Server instead of FastMCP?
  FastMCP uses @mcp.tool() decorators that generate inputSchema from
  Python type hints. Our tools are discovered at RUNTIME from Lambda
  functions — we don't know the schemas at code time. The low-level
  Server class lets us provide our OWN schemas from Lambda __describe__.

Architecture:
  - This module defines the MCP request handlers (list_tools, call_tool)
  - It uses the discovery module to find and invoke tools
  - The main module runs this server with Streamable HTTP transport

Official MCP SDK reference:
  https://github.com/modelcontextprotocol/python-sdk
  Pattern: mcp.server.lowlevel.Server with @server.list_tools() / @server.call_tool()
"""

import json
import logging
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

from app.config import SERVER_NAME
from app.discovery import discover_tools, invoke_tool

logger = logging.getLogger("mcp-server")

# ─── Create the MCP Server Instance ─────────────────────────────
# This is the official way to create a low-level MCP server.
# The Server class manages the JSON-RPC protocol, request routing,
# and response formatting.
server = Server(SERVER_NAME)


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    Handle the MCP 'tools/list' request.

    This is called when a client sends:
        {"jsonrpc":"2.0", "method":"tools/list", "id":1}

    It returns all tools discovered from Lambda functions.
    Each tool includes its name, description, and inputSchema —
    exactly as the tool Lambda reported them via __describe__.

    The MCP SDK automatically wraps this in the proper JSON-RPC response:
        {"jsonrpc":"2.0", "id":1, "result":{"tools":[...]}}
    """
    logger.info("═══ HANDLE tools/list ═══")

    # Get tool registry (cached or fresh discovery)
    registry = discover_tools()

    # Convert our internal registry format to MCP SDK's Tool objects.
    # types.Tool is the official MCP SDK type for tool definitions.
    tools = []
    for tool_name, tool_info in registry.items():
        tool = types.Tool(
            name=tool_name,
            description=tool_info["description"],
            inputSchema=tool_info["input_schema"],
        )
        tools.append(tool)
        logger.debug(f"  Listed tool: {tool_name} (from {tool_info['lambda_name']})")

    logger.info(f"═══ tools/list → returning {len(tools)} tools ═══")
    return tools


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    """
    Handle the MCP 'tools/call' request.

    This is called when a client sends:
        {"jsonrpc":"2.0", "method":"tools/call", "id":2,
         "params":{"name":"add", "arguments":{"a":5, "b":3}}}

    Flow:
        1. Look up which Lambda hosts this tool (from cached registry)
        2. Invoke that Lambda with {"action":"__call__", "tool":"add", "arguments":{...}}
        3. Get the result and wrap it in MCP's TextContent format

    Returns a list of TextContent objects (MCP SDK convention).
    The MCP SDK wraps this in the proper JSON-RPC response.
    """
    logger.info(f"═══ HANDLE tools/call: '{name}' with args: {json.dumps(arguments)} ═══")

    try:
        # Invoke the tool via the discovery module
        result = invoke_tool(name, arguments)

        # Check if the tool returned an error
        if "error" in result:
            error_msg = result["error"]
            logger.error(f"═══ tools/call '{name}' → ERROR: {error_msg} ═══")
            # Return error as text content (MCP convention)
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": error_msg}),
            )]

        # Return successful result as JSON text
        result_json = json.dumps(result)
        logger.info(f"═══ tools/call '{name}' → SUCCESS: {result_json[:200]} ═══")

        return [types.TextContent(type="text", text=result_json)]

    except ValueError as e:
        # Tool not found
        logger.error(f"═══ tools/call '{name}' → NOT FOUND: {e} ═══")
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": str(e)}),
        )]
    except Exception as e:
        # Unexpected error
        logger.error(f"═══ tools/call '{name}' → UNEXPECTED ERROR: {e} ═══", exc_info=True)
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Internal server error: {str(e)}"}),
        )]
