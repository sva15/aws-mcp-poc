# MCP Server on Lambda (Prototype) — For Comparison

This document provides the Lambda-based MCP server prototype used for the ECS vs Lambda evaluation in `06-ecs-vs-lambda-comparison.md`.

> [!NOTE]
> This is an **alternative implementation** for evaluation purposes only. The primary POC uses ECS Fargate (recommended). Deploy this if you want to compare both approaches side-by-side.

---

## How It Works

Instead of running the MCP server on ECS, this version runs the MCP server **as a Lambda function** behind a Lambda Function URL (HTTP endpoint).

```
Client Lambda → HTTPS → Lambda Function URL → MCP Server Lambda → Tool Lambdas
```

### Limitations

| Limitation | Impact |
|-----------|--------|
| Cold starts | ~800ms on first request (Python + boto3) |
| No persistent state | Tool registry re-discovered on every cold start |
| No SSE streaming | Response is synchronous JSON only |
| 15-min timeout | Long-running operations may fail |
| 6 MB payload limit | Large tool results may be truncated |

---

## File: `lambda-mcp-server/lambda_function.py`

```python
"""
MCP Server running as a Lambda Function.
Prototype for ECS vs Lambda comparison.
This is a simplified MCP server that handles JSON-RPC directly.
"""

import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Config
TOOL_LAMBDA_ARNS = os.environ.get("TOOL_LAMBDA_ARNS", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# Global tool registry (persisted between warm invocations)
tool_registry = {}


def discover_tools():
    """Discover tools from configured Lambda functions."""
    global tool_registry

    if tool_registry:
        logger.info("Using cached tool registry")
        return  # Use cached tools from warm invocation

    if not TOOL_LAMBDA_ARNS:
        logger.warning("No TOOL_LAMBDA_ARNS configured")
        return

    lambda_names = [n.strip() for n in TOOL_LAMBDA_ARNS.split(",") if n.strip()]
    logger.info(f"Discovering tools from {len(lambda_names)} Lambdas...")

    for name in lambda_names:
        try:
            response = lambda_client.invoke(
                FunctionName=name,
                InvocationType="RequestResponse",
                Payload=json.dumps({"action": "__describe__"}).encode(),
            )
            payload = json.loads(response["Payload"].read().decode())
            if isinstance(payload, dict) and "body" in payload:
                payload = json.loads(payload["body"]) if isinstance(payload["body"], str) else payload["body"]

            for tool in payload.get("tools", []):
                tool_registry[tool["name"]] = {
                    "lambda_name": name,
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {}),
                }
                logger.info(f"  Registered: {tool['name']}")

        except Exception as e:
            logger.error(f"Failed to discover from {name}: {e}")


def handle_initialize(request_id):
    """Handle MCP initialize request."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "aws-mcp-server-lambda",
                "version": "1.0.0"
            }
        }
    }


def handle_tools_list(request_id):
    """Handle MCP tools/list request."""
    discover_tools()
    tools = []
    for name, info in tool_registry.items():
        tools.append({
            "name": name,
            "description": info["description"],
            "inputSchema": info["input_schema"],
        })

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"tools": tools}
    }


def handle_tools_call(request_id, params):
    """Handle MCP tools/call request."""
    discover_tools()
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name not in tool_registry:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
        }

    tool_info = tool_registry[tool_name]

    try:
        response = lambda_client.invoke(
            FunctionName=tool_info["lambda_name"],
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "action": "__call__",
                "tool": tool_name,
                "arguments": arguments,
            }).encode(),
        )
        result = json.loads(response["Payload"].read().decode())
        if isinstance(result, dict) and "body" in result:
            result = json.loads(result["body"]) if isinstance(result["body"], str) else result["body"]

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(result)}
                ]
            }
        }

    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32603, "message": str(e)}
        }


def lambda_handler(event, context):
    """
    Lambda Function URL handler.
    Expects JSON-RPC requests in the body.
    """
    # Parse the request body
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    method = body.get("method", "")
    request_id = body.get("id", 1)
    params = body.get("params", {})

    logger.info(f"Received method: {method}")

    # Route to handler
    if method == "initialize":
        result = handle_initialize(request_id)
    elif method == "tools/list":
        result = handle_tools_list(request_id)
    elif method == "tools/call":
        result = handle_tools_call(request_id, params)
    elif method == "notifications/initialized":
        result = {"jsonrpc": "2.0", "id": request_id, "result": {}}
    else:
        result = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result)
    }
```

---

## Deployment Steps (AWS Console)

### Step 1: Create the Lambda Function

1. Go to **Lambda Console** → **Create Function**
2. **Function name**: `mcp-server-lambda`
3. **Runtime**: Python 3.12
4. **Execution role**: Create new role with `AWSLambdaBasicExecutionRole`
5. After creation, add inline policy to the role:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": "arn:aws:lambda:*:*:function:mcp-tool-*"
        }
    ]
}
```

### Step 2: Configure Function

1. **Code**: Paste the Lambda function code above
2. **Configuration** → **General**:
   - Timeout: `60 seconds`
   - Memory: `256 MB`
3. **Configuration** → **Environment variables**:
   - `TOOL_LAMBDA_ARNS`: `mcp-tool-math,mcp-tool-string`
   - `AWS_REGION`: `us-east-1`

### Step 3: Create Function URL

1. Go to **Configuration** → **Function URL** → **Create function URL**
2. **Auth type**: NONE (for POC)
3. Copy the Function URL (e.g., `https://abc123.lambda-url.us-east-1.on.aws`)

### Step 4: Test

```bash
# Test Initialize
curl -X POST https://YOUR-FUNCTION-URL \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# Test List Tools
curl -X POST https://YOUR-FUNCTION-URL \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Test Call Tool
curl -X POST https://YOUR-FUNCTION-URL \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"add","arguments":{"a":10,"b":20}}}'
```

---

## Using This with the Client Lambda

To test the Lambda-based MCP server with the client Lambda:

1. Update the Client Lambda's `MCP_SERVER_URL` to the Lambda Function URL
2. **Note**: The client code works with both ECS and Lambda versions because both speak JSON-RPC

---

## Comparison Notes

After deploying both:
- Run `full_test` against ECS-based server → record latency
- Run `full_test` against Lambda-based server → record latency
- Check CloudWatch metrics for both
- Fill in the actual measured values in `06-ecs-vs-lambda-comparison.md`
