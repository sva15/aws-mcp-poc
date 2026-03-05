"""
Tool Discovery Module — Cloud-Agnostic (HTTP-only).

This module discovers tools by calling a Tool Registry service via HTTP
and invokes tools by calling their HTTP URLs directly.

Architecture:
  MCP Server → HTTP POST → Tool Registry (/registry)  → tool list + URLs
  MCP Server → HTTP POST → Tool URL     (/tools/math) → tool execution

No AWS SDK (boto3) used here. Any HTTP-accessible service works:
  - Lambda behind ALB or API Gateway
  - Azure Functions
  - GCP Cloud Functions
  - Plain Docker/K8s services

Protocol (same as before, but over HTTP instead of Lambda Invoke):
  - Discover: POST {url} {"action":"__describe__"} → {"tools":[...]}
  - Call:     POST {url} {"action":"__call__","tool":"add","arguments":{...}} → result

Registry Protocol:
  - List:     POST /registry {"action":"list"} → {"providers":[{name, url, tools:[...]}, ...]}
  - Register: POST /registry {"action":"register","provider":{name, url}} → OK
"""

import json
import time
import logging
from typing import Any

import httpx

from app.config import REGISTRY_URL, CACHE_TTL_SECONDS

logger = logging.getLogger("discovery")

# ─── Module-Level Cache ──────────────────────────────────────────
# These persist between requests within the same container/process.
# The container stays alive, so the cache survives across requests
# until TTL expires or container restarts.

_tool_registry: dict[str, dict[str, Any]] = {}
_last_discovery_time: float = 0.0

# HTTP client — created once, reused across requests.
# httpx is already a dependency of the MCP SDK, so no extra install needed.
_http_client = httpx.Client(timeout=30.0)


def discover_tools(force: bool = False) -> dict[str, dict[str, Any]]:
    """
    Discover tools from the Tool Registry via HTTP.

    This is the main entry point. It checks the cache first, and only
    calls the registry when the cache is expired or force=True.

    Args:
        force: If True, bypass cache and query registry immediately.

    Returns:
        Dictionary mapping tool_name → tool_info dict containing:
          - provider_url: HTTP URL to call this tool
          - description: Human-readable description
          - input_schema: JSON Schema for the tool's parameters

    Internal flow:
        1. Check if cache is still valid (within TTL)
        2. If valid, return cached registry immediately
        3. If expired (or force), call _query_registry()
        4. Registry returns providers with their tool definitions
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
        f"Querying Tool Registry at {REGISTRY_URL}"
    )

    # ── Step 1: Query the Tool Registry ──────────────────────────
    providers = _query_registry()

    if not providers:
        logger.warning(
            f"No tool providers returned from registry at {REGISTRY_URL}. "
            "Check that the registry is running and accessible."
        )
        if _tool_registry:
            logger.warning("Keeping stale cache as fallback")
            return _tool_registry
        return {}

    # ── Step 2: Build the tool registry from provider data ───────
    new_registry: dict[str, dict[str, Any]] = {}

    for provider in providers:
        provider_name = provider.get("name", "unknown")
        provider_url = provider.get("url", "")
        tools = provider.get("tools", [])

        logger.info(f"  Provider '{provider_name}' at {provider_url}: {len(tools)} tools")

        for tool_def in tools:
            tool_name = tool_def["name"]
            new_registry[tool_name] = {
                "provider_name": provider_name,
                "provider_url": provider_url,
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
        f"{len(providers)} providers → {list(_tool_registry.keys())}"
    )

    return _tool_registry


def _query_registry() -> list[dict[str, Any]]:
    """
    Call the Tool Registry HTTP endpoint to get all registered providers.

    Sends: POST {REGISTRY_URL} {"action":"list"}
    Expects: {"providers":[{"name":"math","url":"http://...","tools":[...]}, ...]}

    Returns: List of provider dicts with their tool definitions.
    """
    try:
        logger.info(f"  Calling registry: POST {REGISTRY_URL}")

        response = _http_client.post(
            REGISTRY_URL,
            json={"action": "list"},
            headers={"Content-Type": "application/json"},
        )

        logger.info(f"  Registry response: HTTP {response.status_code}")

        if response.status_code != 200:
            logger.error(
                f"  Registry returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
            return []

        data = response.json()

        # Handle ALB-wrapped responses (statusCode/body)
        if isinstance(data, dict) and "body" in data:
            body = data["body"]
            data = json.loads(body) if isinstance(body, str) else body

        providers = data.get("providers", [])
        logger.info(f"  Registry returned {len(providers)} providers")
        return providers

    except httpx.ConnectError as e:
        logger.error(f"  Cannot connect to registry at {REGISTRY_URL}: {e}")
        return []
    except httpx.TimeoutException as e:
        logger.error(f"  Timeout calling registry at {REGISTRY_URL}: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"  Invalid JSON from registry: {e}")
        return []
    except Exception as e:
        logger.error(f"  Unexpected error querying registry: {e}")
        return []


def invoke_tool(tool_name: str, arguments: dict) -> dict[str, Any]:
    """
    Invoke a tool by calling its HTTP URL directly.

    The tool's URL comes from the registry (cached in _tool_registry).
    This sends the __call__ protocol over HTTP POST.

    Args:
        tool_name: Name of the tool to invoke (e.g., "add")
        arguments: Tool arguments (e.g., {"a": 5, "b": 3})

    Returns:
        The tool's result dict. Contains either {"result":...} or {"error":...}
    """
    registry = discover_tools()  # Uses cache automatically

    if tool_name not in registry:
        available = list(registry.keys())
        logger.error(f"TOOL NOT FOUND: '{tool_name}'. Available: {available}")
        raise ValueError(f"Unknown tool: '{tool_name}'. Available: {available}")

    tool_info = registry[tool_name]
    provider_url = tool_info["provider_url"]
    provider_name = tool_info["provider_name"]

    logger.info(
        f"INVOKE TOOL: '{tool_name}' → provider '{provider_name}' "
        f"at {provider_url} with args: {json.dumps(arguments)}"
    )

    try:
        response = _http_client.post(
            provider_url,
            json={
                "action": "__call__",
                "tool": tool_name,
                "arguments": arguments,
            },
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            error_msg = f"HTTP {response.status_code} from {provider_url}: {response.text[:200]}"
            logger.error(f"TOOL ERROR: {error_msg}")
            return {"error": error_msg}

        result = response.json()

        # Handle ALB-wrapped responses
        if isinstance(result, dict) and "body" in result:
            body = result["body"]
            result = json.loads(body) if isinstance(body, str) else body

        logger.info(f"TOOL RESULT: '{tool_name}' → {json.dumps(result)[:200]}")
        return result

    except httpx.ConnectError as e:
        error_msg = f"Cannot connect to {provider_url}: {e}"
        logger.error(f"TOOL ERROR: {error_msg}")
        return {"error": error_msg}
    except httpx.TimeoutException as e:
        error_msg = f"Timeout calling {provider_url}: {e}"
        logger.error(f"TOOL ERROR: {error_msg}")
        return {"error": error_msg}
    except Exception as e:
        error_msg = f"Error invoking tool '{tool_name}': {str(e)}"
        logger.error(f"TOOL ERROR: {error_msg}")
        return {"error": error_msg}
