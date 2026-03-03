"""
MCP Server Entry Point.

This is the main module that wires everything together:
  1. Creates the MCP Server (from server.py)
  2. Wraps it in a Starlette ASGI app with Streamable HTTP transport
  3. Adds a /health endpoint for ALB health checks
  4. Runs the initial tool discovery
  5. Starts the server via uvicorn

Architecture notes:
  - We use FastMCP's streamable_http_app() to get the ASGI app
  - We wrap our low-level Server inside a FastMCP instance for transport
  - The low-level Server handles list_tools/call_tool with OUR schemas
  - FastMCP just provides the HTTP transport layer

Official MCP SDK reference for Streamable HTTP:
  FastMCP(stateless_http=True, json_response=True) for production
  mcp.run(transport="streamable-http") for standalone
"""

import logging
import json
import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount

from mcp.server.fastmcp import FastMCP

from app.config import SERVER_NAME, SERVER_HOST, SERVER_PORT, SERVER_VERSION
from app.server import server as mcp_low_level_server
from app.discovery import discover_tools

logger = logging.getLogger("main")


# ─── Create FastMCP Wrapper for HTTP Transport ──────────────────
# We use FastMCP as a transport layer only. The actual tool handling
# is done by our low-level Server (app/server.py).
#
# Why this pattern?
#   - FastMCP provides production-ready Streamable HTTP transport
#   - Our low-level Server handles tools with custom schemas
#   - Best of both worlds: proper transport + dynamic schemas
#
# stateless_http=True: No session state → works behind load balancer
# json_response=True:  Pure JSON responses → simple and predictable
mcp_app = FastMCP(
    name=SERVER_NAME,
    stateless_http=True,
    json_response=True,
)

# Replace FastMCP's internal server with our low-level server.
# This makes FastMCP use OUR list_tools/call_tool handlers
# while still providing the Streamable HTTP transport.
mcp_app._mcp_server = mcp_low_level_server


# ─── Health Check Endpoint ──────────────────────────────────────
# Required for ALB health checks in ECS. The ALB pings this endpoint
# every 30 seconds. If it returns non-200, the container is replaced.

async def health_check(request: Request) -> JSONResponse:
    """
    Health check endpoint for ALB.

    Returns basic server info and the number of discovered tools.
    The ALB checks this to ensure the container is healthy.
    """
    registry = discover_tools()  # Uses cache, no re-scan
    return JSONResponse({
        "status": "healthy",
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "tools_discovered": len(registry),
        "tool_names": list(registry.keys()),
    })


# ─── Startup: Initial Tool Discovery ───────────────────────────

@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    """
    Application lifespan handler.

    Runs tool discovery on startup so the first client request
    doesn't have to wait for discovery. Also initializes the
    FastMCP session manager.
    """
    logger.info("=" * 60)
    logger.info(f"  MCP Server '{SERVER_NAME}' v{SERVER_VERSION} starting")
    logger.info(f"  Endpoint: http://{SERVER_HOST}:{SERVER_PORT}/mcp")
    logger.info(f"  Health:   http://{SERVER_HOST}:{SERVER_PORT}/health")
    logger.info("=" * 60)

    # Run initial tool discovery
    logger.info("Running initial tool discovery...")
    registry = discover_tools(force=True)
    logger.info(f"Initial discovery complete: {len(registry)} tools found")

    for tool_name, tool_info in registry.items():
        logger.info(
            f"  • {tool_name:20s} ← {tool_info['lambda_name']:25s} "
            f"│ {tool_info['description'][:60]}"
        )

    logger.info("=" * 60)
    logger.info("  Server ready to accept connections")
    logger.info("=" * 60)

    # Start the FastMCP session manager
    async with mcp_app.session_manager.run():
        yield


# ─── Assemble the ASGI Application ─────────────────────────────
# Starlette lets us combine the MCP endpoint and health check
# into one application running on one port.

app = Starlette(
    routes=[
        # MCP Streamable HTTP endpoint
        # Clients connect to: http://<host>:8000/mcp
        Mount("/mcp", app=mcp_app.streamable_http_app()),

        # ALB health check endpoint
        Route("/health", health_check, methods=["GET"]),
    ],
    lifespan=lifespan,
)


# ─── CLI Entry Point ────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"Starting uvicorn on {SERVER_HOST}:{SERVER_PORT}")

    uvicorn.run(
        "app.main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="info",
        # In production, set workers > 1 for multi-process
        # But each worker does its own discovery (acceptable with caching)
    )
