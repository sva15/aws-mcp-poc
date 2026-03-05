"""
MCP Server — Uses the official MCP Python SDK's low-level Server API.

Why low-level Server instead of FastMCP with @mcp.tool()?
==========================================================

The @mcp.tool() decorator (FastMCP) is designed for STATIC tools:
  @mcp.tool()
  def add(a: int, b: int) -> int:
      return a + b

FastMCP reads the Python type hints (a: int, b: int) and auto-generates
the JSON Schema (inputSchema). This is great when tools are written
directly inside the server code.

BUT our tools are DYNAMIC — they live in EXTERNAL services (behind ALB).
We don't know what tools exist until we ask the Tool Registry at runtime.
We can't decorate something that doesn't exist in our code.

The low-level Server class lets us:
  1. @server.list_tools() → return ANY list of tools with ANY schemas
  2. @server.call_tool()  → route to ANY external service via HTTP

This is the pattern for tool brokers, proxy servers, and dynamic registries.

Architecture:
  Client → MCP Server (this) → Tool Registry (list) → Tool URLs (call)
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
# The Server class manages JSON-RPC protocol, request routing,
# and response formatting. It is cloud-agnostic.
server = Server(SERVER_NAME)


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    Handle the MCP 'tools/list' request.

    Called when a client sends:
        {"jsonrpc":"2.0", "method":"tools/list", "id":1}

    Returns all tools discovered from the Tool Registry.
    Each tool includes name, description, and inputSchema
    exactly as the tool provider reported them.

    The MCP SDK wraps this in the JSON-RPC response:
        {"jsonrpc":"2.0", "id":1, "result":{"tools":[...]}}
    """
    logger.info("═══ HANDLE tools/list ═══")

    registry = discover_tools()

    tools = []
    for tool_name, tool_info in registry.items():
        tool = types.Tool(
            name=tool_name,
            description=tool_info["description"],
            inputSchema=tool_info["input_schema"],
        )
        tools.append(tool)
        logger.debug(f"  Listed: {tool_name} (provider: {tool_info['provider_name']})")

    logger.info(f"═══ tools/list → returning {len(tools)} tools ═══")
    return tools


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    """
    Handle the MCP 'tools/call' request.

    Called when a client sends:
        {"jsonrpc":"2.0", "method":"tools/call", "id":2,
         "params":{"name":"add", "arguments":{"a":5, "b":3}}}

    Flow:
        1. Look up the tool's provider URL (from cache)
        2. HTTP POST to the provider with __call__ protocol
        3. Return the result wrapped in MCP TextContent format
    """
    logger.info(f"═══ HANDLE tools/call: '{name}' with args: {json.dumps(arguments)} ═══")

    try:
        result = invoke_tool(name, arguments)

        if "error" in result:
            error_msg = result["error"]
            logger.error(f"═══ tools/call '{name}' → ERROR: {error_msg} ═══")
            return [types.TextContent(type="text", text=json.dumps({"error": error_msg}))]

        result_json = json.dumps(result)
        logger.info(f"═══ tools/call '{name}' → SUCCESS: {result_json[:200]} ═══")
        return [types.TextContent(type="text", text=result_json)]

    except ValueError as e:
        logger.error(f"═══ tools/call '{name}' → NOT FOUND: {e} ═══")
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]
    except Exception as e:
        logger.error(f"═══ tools/call '{name}' → UNEXPECTED ERROR: {e} ═══", exc_info=True)
        return [types.TextContent(type="text", text=json.dumps({"error": f"Internal error: {str(e)}"}))
        ]
