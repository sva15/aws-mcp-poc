"""
Configuration module for the MCP Server.

All settings are loaded from environment variables with sensible defaults.
This keeps configuration separate from logic (12-factor app principle).
"""

import os
import logging

# ─── Logging Configuration ───────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)

# ─── AWS Configuration ──────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# ─── Tool Discovery Configuration ───────────────────────────────
# Prefix used to identify tool Lambda functions.
# Any Lambda matching this prefix will be discovered automatically.
TOOL_PREFIX = os.environ.get("TOOL_PREFIX", "mcp-tool-")

# Time-to-live for the tool cache, in seconds.
# After this period, the next tools/list request triggers re-discovery.
# Set to 0 to disable caching (discover on every request).
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL", "300"))

# ─── Server Configuration ───────────────────────────────────────
SERVER_NAME = os.environ.get("SERVER_NAME", "aws-mcp-server")
SERVER_VERSION = os.environ.get("SERVER_VERSION", "1.0.0")
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8085"))
