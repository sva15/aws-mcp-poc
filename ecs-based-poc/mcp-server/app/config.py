"""
MCP Server Configuration — Cloud-Agnostic.

All settings loaded from environment variables (12-factor app).
No AWS-specific configuration here — the server only knows HTTP URLs.

Key difference from the previous version:
  Before: AWS_REGION, TOOL_PREFIX (scanned Lambda functions via boto3)
  After:  REGISTRY_URL (calls a Tool Registry via HTTP)
"""

import os
import logging

# ─── Logging ─────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ─── Tool Registry (cloud-agnostic) ──────────────────────────────
# URL of the Tool Registry service. This is the ONLY external
# dependency for tool discovery. The registry can be:
#   - Lambda behind ALB     (AWS)
#   - Azure Function        (Azure)
#   - Cloud Run             (GCP)
#   - Any HTTP service      (on-prem / K8s)
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://tools-alb.example.com/registry")

# Cache TTL for discovered tools. The MCP server caches tool
# definitions to avoid calling the registry on every request.
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))

# ─── Server Identity ─────────────────────────────────────────────
SERVER_NAME = os.environ.get("SERVER_NAME", "mcp-server")
SERVER_VERSION = os.environ.get("SERVER_VERSION", "1.0.0")
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8085"))
