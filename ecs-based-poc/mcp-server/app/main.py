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


# ─── Host Header Middleware ──────────────────────────────────────
# The MCP SDK's Streamable HTTP transport has DNS rebinding protection:
# it validates the Host header and rejects anything that isn't "localhost".
#
# When accessing via IP (e.g., 10.132.191.157), the Host header is the IP,
# which gets rejected with: 421 "Invalid Host header"
#
# This middleware rewrites the Host header to "localhost" BEFORE the
# request reaches the MCP SDK, bypassing this check.
#
# This is SAFE for private EC2 deployments where:
#   - The server is on a private subnet (not internet-facing)
#   - DNS rebinding attacks are not a concern
#   - Access is controlled by security groups

class HostHeaderMiddleware:
    """
    ASGI middleware that rewrites the Host header to localhost.
    Fixes: 421 "Invalid Host header" from MCP SDK's DNS rebinding protection.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Rewrite the Host header to localhost so MCP SDK accepts it
            new_headers = []
            for key, value in scope.get("headers", []):
                if key == b"host":
                    new_headers.append((b"host", f"localhost:{SERVER_PORT}".encode()))
                else:
                    new_headers.append((key, value))
            scope = dict(scope, headers=new_headers)

        await self.app(scope, receive, send)


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
#
# IMPORTANT: streamable_http_app() already creates an internal
# route at "/mcp". If we Mount("/mcp", ...), Starlette strips
# the "/mcp" prefix → sub-app sees "/" → no match → 307 redirect.
#
# Fix: Mount at "/" so the sub-app's internal "/mcp" route works.
# Requests flow:  POST /mcp → Starlette "/" mount → sub-app "/mcp" → OK

_starlette_app = Starlette(
    routes=[
        # Health check endpoint (must be BEFORE the catch-all Mount)
        Route("/health", health_check, methods=["GET"]),

        # MCP Streamable HTTP endpoint
        # Clients connect to: http://<host>:8085/mcp
        # The streamable_http_app() handles /mcp internally
        Mount("/", app=mcp_app.streamable_http_app()),
    ],
    lifespan=lifespan,
)

# Wrap with HostHeaderMiddleware to fix 421 "Invalid Host header"
# when accessing via IP address instead of localhost
app = HostHeaderMiddleware(_starlette_app)


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
