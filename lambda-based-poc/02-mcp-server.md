# MCP Server Lambda — Dynamic Tool Discovery

This document explains the MCP Server Lambda function in detail.

---

## What the MCP Server Does

The MCP Server is a **Lambda function** that acts as the central hub:

1. **Discovers tools automatically** — scans all Lambda functions named `mcp-tool-*`
2. **Serves tool list** — responds to `tools/list` with all discovered tools
3. **Executes tools** — responds to `tools/call` by invoking the correct tool Lambda

```
                        MCP Server Lambda
                    ┌────────────────────────┐
                    │                        │
  tools/list ──────▶│  1. list_functions()   │
                    │  2. Filter mcp-tool-*  │
                    │  3. __describe__ each  │
                    │  4. Return all tools   │
                    │                        │
  tools/call ──────▶│  1. Find tool Lambda   │
  (tool: "add",     │  2. Invoke with __call_│
   args: {a:5,b:3}) │  3. Return result      │
                    │                        │
                    └────────────────────────┘
```

---

## Dynamic Discovery — Deep Dive

### How It Works (Step by Step)

```python
# Step 1: List all Lambda functions in the account
response = lambda_client.list_functions()

# Step 2: Filter by naming convention
tool_lambdas = [f for f in response["Functions"] 
                if f["FunctionName"].startswith("mcp-tool-")]

# Result: ["mcp-tool-math", "mcp-tool-string", "mcp-tool-time"]

# Step 3: Call __describe__ on each one
for lambda_name in tool_lambdas:
    result = lambda_client.invoke(
        FunctionName=lambda_name,
        Payload=json.dumps({"action": "__describe__"})
    )
    # Collect the tool definitions
    
# Step 4: Build combined registry
# {
#   "add":       {"lambda": "mcp-tool-math",   "description": "...", "schema": {...}},
#   "multiply":  {"lambda": "mcp-tool-math",   "description": "...", "schema": {...}},
#   "uppercase": {"lambda": "mcp-tool-string", "description": "...", "schema": {...}},
#   "now":       {"lambda": "mcp-tool-time",   "description": "...", "schema": {...}},
# }
```

### Why This Is Powerful

**Traditional approach (hardcoded):**
```
Deploy new tool Lambda → Update MCP server config → Redeploy MCP server → Test
```

**Our approach (dynamic):**
```
Deploy new tool Lambda (named mcp-tool-*) → Done. It's automatically discovered.
```

### Caching for Performance

The tool registry is cached in the Lambda's global scope (module-level variable). This means:

| Scenario | Behavior |
|----------|----------|
| **Cold start** | Full discovery — scans all tool Lambdas (~500ms) |
| **Warm invocation** | Uses cached registry (~0ms) |
| **New tool added** | On next cold start, or when cache expires (TTL) |
| **Force refresh** | Pass `force_refresh: true` in the request |

We use a **TTL (Time To Live)** of 5 minutes. After 5 minutes, the next request triggers a fresh discovery.

---

## Complete Code: `mcp-server/lambda_function.py`

```python
"""
MCP Server Lambda — Dynamic Tool Discovery
Automatically discovers all mcp-tool-* Lambda functions and serves their tools.
"""

import os
import json
import time
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TOOL_PREFIX = os.environ.get("TOOL_PREFIX", "mcp-tool-")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))  # 5 minutes

lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# ──────────────────────────────────────────────
# Global cache (persists between warm invocations)
# ──────────────────────────────────────────────
_tool_registry = {}      # tool_name -> {lambda_name, description, input_schema}
_last_discovery = 0       # timestamp of last discovery


def discover_tools(force=False):
    """
    Discover all tools from Lambda functions matching the prefix.
    Uses caching to avoid re-scanning on every request.
    """
    global _tool_registry, _last_discovery

    # Check cache validity
    if not force and _tool_registry and (time.time() - _last_discovery) < CACHE_TTL:
        logger.info(f"Using cached tool registry ({len(_tool_registry)} tools)")
        return _tool_registry

    logger.info(f"Starting tool discovery (prefix: {TOOL_PREFIX})...")
    new_registry = {}

    try:
        # Step 1: List all Lambda functions (handles pagination)
        tool_lambdas = []
        paginator = lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            for func in page["Functions"]:
                if func["FunctionName"].startswith(TOOL_PREFIX):
                    tool_lambdas.append(func["FunctionName"])

        logger.info(f"Found {len(tool_lambdas)} tool Lambdas: {tool_lambdas}")

        # Step 2: Query each tool Lambda for its tool definitions
        for lambda_name in tool_lambdas:
            try:
                logger.info(f"  Querying: {lambda_name}")
                response = lambda_client.invoke(
                    FunctionName=lambda_name,
                    InvocationType="RequestResponse",
                    Payload=json.dumps({"action": "__describe__"}).encode(),
                )
                payload = json.loads(response["Payload"].read().decode())

                # Handle wrapped response
                if isinstance(payload, dict) and "body" in payload:
                    payload = (json.loads(payload["body"]) 
                              if isinstance(payload["body"], str) 
                              else payload["body"])

                # Register each tool
                for tool_def in payload.get("tools", []):
                    tool_name = tool_def["name"]
                    new_registry[tool_name] = {
                        "lambda_name": lambda_name,
                        "description": tool_def.get("description", ""),
                        "input_schema": tool_def.get("input_schema", {}),
                    }
                    logger.info(f"    ✓ Registered: {tool_name}")

            except Exception as e:
                logger.error(f"  ✗ Failed to query {lambda_name}: {e}")

    except Exception as e:
        logger.error(f"Failed to list Lambda functions: {e}")
        if _tool_registry:
            logger.warning("Falling back to stale cache")
            return _tool_registry

    _tool_registry = new_registry
    _last_discovery = time.time()
    logger.info(f"Discovery complete: {len(_tool_registry)} tools registered")
    return _tool_registry


def invoke_tool(tool_name, arguments):
    """Invoke a specific tool on its Lambda function."""
    registry = discover_tools()

    if tool_name not in registry:
        return {"error": f"Unknown tool: {tool_name}. Available: {list(registry.keys())}"}

    tool_info = registry[tool_name]
    lambda_name = tool_info["lambda_name"]

    logger.info(f"Invoking tool '{tool_name}' on Lambda '{lambda_name}'")

    response = lambda_client.invoke(
        FunctionName=lambda_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "action": "__call__",
            "tool": tool_name,
            "arguments": arguments,
        }).encode(),
    )

    result = json.loads(response["Payload"].read().decode())

    # Handle wrapped response
    if isinstance(result, dict) and "body" in result:
        result = (json.loads(result["body"]) 
                 if isinstance(result["body"], str) 
                 else result["body"])

    logger.info(f"Tool '{tool_name}' returned: {result}")
    return result


# ──────────────────────────────────────────────
# JSON-RPC Request Handlers
# ──────────────────────────────────────────────

def handle_initialize(request_id):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-server-lambda", "version": "1.0.0"},
        },
    }


def handle_tools_list(request_id, params):
    force = params.get("force_refresh", False)
    registry = discover_tools(force=force)

    tools = []
    for name, info in registry.items():
        tools.append({
            "name": name,
            "description": info["description"],
            "inputSchema": info["input_schema"],
        })

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"tools": tools},
    }


def handle_tools_call(request_id, params):
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    result = invoke_tool(tool_name, arguments)

    if "error" in result:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": result["error"]},
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(result)}],
        },
    }


# ──────────────────────────────────────────────
# Lambda Entry Point
# ──────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Main handler for MCP Server.
    Accepts JSON-RPC requests either directly or via Lambda Function URL.
    """
    # Parse body (handles both direct invoke and Function URL)
    if isinstance(event, str):
        event = json.loads(event)

    body = event
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            body = json.loads(body)

    method = body.get("method", "")
    request_id = body.get("id", 1)
    params = body.get("params", {})

    logger.info(f"MCP Server received: method={method}")

    # Route to handler
    handlers = {
        "initialize": lambda: handle_initialize(request_id),
        "notifications/initialized": lambda: {"jsonrpc": "2.0", "id": request_id, "result": {}},
        "tools/list": lambda: handle_tools_list(request_id, params),
        "tools/call": lambda: handle_tools_call(request_id, params),
    }

    handler = handlers.get(method)
    if handler:
        response = handler()
    else:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response),
    }
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region where tool Lambdas are deployed |
| `TOOL_PREFIX` | `mcp-tool-` | Prefix used to identify tool Lambda functions |
| `CACHE_TTL` | `300` | Seconds to cache the tool registry (0 = no cache) |

---

## How the Caching Works

```
Request 1 (T=0s)     → Cold start → Full discovery (scans 3 Lambdas) → 500ms
Request 2 (T=2s)     → Warm → Uses cache → 0ms discovery
Request 3 (T=60s)    → Warm → Uses cache → 0ms discovery
Request 4 (T=301s)   → Warm → Cache expired → Re-discovery → 200ms
...
Request N (T=900s)   → Cold start (Lambda recycled) → Full discovery → 500ms
```

### Force Refresh

If you deploy a new tool Lambda and want immediate discovery:

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {"force_refresh": true}
}
```

---

## Error Handling

| Error | Cause | Behavior |
|-------|-------|----------|
| Lambda not found | Tool Lambda was deleted | Tool removed from registry on next discovery |
| Lambda timeout | Tool Lambda takes too long | Error returned to client |
| Permission denied | Missing IAM permissions | Error logged, tool skipped |
| Stale cache | New tool not yet discovered | Auto-resolves on cache expiry or force refresh |

---

**Next →** [03-tool-lambdas.md](./03-tool-lambdas.md) — Tool Lambda functions
