# MCP Server Code — Python + Dockerfile

This document contains the complete MCP server code that runs on ECS Fargate.

---

## How It Works

The MCP server:
1. **Starts as a FastAPI HTTP server** on port 8000
2. **Reads `TOOL_LAMBDA_ARNS`** environment variable — a comma-separated list of Lambda function names that provide tools
3. **On `tools/list`** — invokes each tool Lambda with `{"action": "__describe__"}` to discover available tools
4. **On `tools/call`** — finds which Lambda owns the requested tool and invokes it with `{"action": "__call__", "tool": "...", "arguments": {...}}`

---

## File 1: `mcp-server/requirements.txt`

```txt
mcp[cli]>=1.2.0
fastapi>=0.115.0
uvicorn>=0.34.0
boto3>=1.35.0
```

> **Note:** `mcp[cli]` installs the official MCP Python SDK with Streamable HTTP support.

---

## File 2: `mcp-server/server.py`

```python
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
    We need this factory function to capture the correct tool_name/lambda_name
    in the closure.
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

        # Build parameter descriptions from input schema
        params = []
        schema = tool_info.get("input_schema", {})
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        for param_name, param_info in properties.items():
            param_type = param_info.get("type", "string")
            param_desc = param_info.get("description", "")
            params.append(f"  {param_name} ({param_type}): {param_desc}")

        description = tool_info["description"]
        if params:
            description += "\n\nParameters:\n" + "\n".join(params)

        # Register with MCP using the low-level API
        mcp.tool(name=tool_name, description=tool_info["description"])(handler)

        logger.info(f"Registered MCP tool: {tool_name}")


# ──────────────────────────────────────────────
# Health Check Endpoint
# ──────────────────────────────────────────────
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    from starlette.responses import JSONResponse
    return JSONResponse({
        "status": "healthy",
        "tools_count": len(tool_registry),
        "tools": list(tool_registry.keys()),
    })


# ──────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────
# Discover and register tools on import/startup
discover_tools()
register_tools()

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting MCP Server on port 8000...")
    # Run with streamable-http transport
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

---

## File 3: `mcp-server/Dockerfile`

```dockerfile
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server.py .

# Expose the port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the server
CMD ["python", "server.py"]
```

---

## Key Design Decisions

### Why FastMCP?

`FastMCP` is the high-level API from the official MCP Python SDK. It provides:
- Automatic JSON-RPC handling
- Built-in Streamable HTTP transport
- Tool registration via decorators or programmatic API
- Session management

### Why Dynamic Tool Registration?

Instead of hardcoding tools in the server, we:
1. Read Lambda function names from an environment variable
2. Query each Lambda to discover its tools at startup
3. Dynamically register them with MCP

This means **you can add new tools by deploying new Lambdas** and updating the `TOOL_LAMBDA_ARNS` env var — no MCP server code changes needed.

### Tool Discovery Protocol

Each tool Lambda must respond to this contract:

**Request: `{"action": "__describe__"}`**
```json
{
  "tools": [
    {
      "name": "add",
      "description": "Add two numbers together",
      "input_schema": {
        "type": "object",
        "properties": {
          "a": {"type": "number", "description": "First number"},
          "b": {"type": "number", "description": "Second number"}
        },
        "required": ["a", "b"]
      }
    }
  ]
}
```

**Request: `{"action": "__call__", "tool": "add", "arguments": {"a": 5, "b": 3}}`**
```json
{
  "result": 8
}
```

---

**Next:** Go to [03-tool-lambda-functions.md](./03-tool-lambda-functions.md) for tool Lambda implementations.
