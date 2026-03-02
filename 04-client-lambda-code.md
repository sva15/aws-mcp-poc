# Client Lambda Function — Code & Setup

This document covers the MCP client Lambda that connects to the MCP server, discovers tools, and invokes them.

---

## How the Client Works

The client Lambda is a **simple HTTP client** that speaks JSON-RPC to the MCP server:

```
┌─────────────────┐     HTTP POST        ┌──────────────────┐
│  Client Lambda   │ ──────────────────▶ │  MCP Server      │
│                  │     /mcp             │  (ECS Fargate)   │
│  1. initialize   │                     │                  │
│  2. tools/list   │ ◀────────────────── │  Returns tools   │
│  3. tools/call   │ ◀────────────────── │  Returns results │
└─────────────────┘                      └──────────────────┘
```

> **No external dependencies required!** The client uses Python's built-in `urllib` — no pip packages needed.

---

## File: `client-lambda/lambda_function.py`

```python
"""
MCP Client Lambda Function
Connects to MCP Server on ECS Fargate via HTTP.
"""

import os
import json
import logging
from urllib import request, error

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000")
MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

logger = logging.getLogger("mcp-client")


def send_mcp_request(method: str, params: dict = None) -> dict:
    """Send a JSON-RPC request to the MCP server."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    req = request.Request(MCP_ENDPOINT, data=data, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")

            if "text/event-stream" in content_type:
                return parse_sse_response(response_body)
            return json.loads(response_body)

    except error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def parse_sse_response(body: str) -> dict:
    """Parse Server-Sent Events response."""
    last_data = None
    for line in body.strip().split("\n"):
        if line.strip().startswith("data: "):
            last_data = line.strip()[6:]
    if last_data:
        try:
            return json.loads(last_data)
        except json.JSONDecodeError:
            return {"raw_data": last_data}
    return {"error": "No data in SSE response"}


def lambda_handler(event, context):
    """
    Supports actions:
    - "list_tools": Discover all available tools
    - "call_tool": Call a specific tool
    - "full_test": List tools + call each one
    """
    action = event.get("action", "full_test")
    results = {}

    # Step 1: Initialize
    init_response = send_mcp_request("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "aws-lambda-mcp-client", "version": "1.0.0"}
    })
    results["initialize"] = init_response

    if action in ("list_tools", "full_test"):
        # Step 2: List tools
        tools_response = send_mcp_request("tools/list")
        results["tools_list"] = tools_response

    if action == "call_tool":
        tool_name = event.get("tool_name", "add")
        arguments = event.get("arguments", {"a": 5, "b": 3})
        call_response = send_mcp_request("tools/call", {
            "name": tool_name, "arguments": arguments
        })
        results["tool_call"] = {
            "tool": tool_name,
            "arguments": arguments,
            "response": call_response,
        }

    elif action == "full_test":
        # Step 3: Call each tool
        test_calls = [
            {"tool": "add", "arguments": {"a": 10, "b": 20}},
            {"tool": "multiply", "arguments": {"a": 7, "b": 6}},
            {"tool": "uppercase", "arguments": {"text": "hello mcp"}},
            {"tool": "reverse", "arguments": {"text": "aws lambda"}},
        ]
        results["tool_calls"] = []
        for test in test_calls:
            call_response = send_mcp_request("tools/call", {
                "name": test["tool"], "arguments": test["arguments"]
            })
            results["tool_calls"].append({
                "tool": test["tool"],
                "arguments": test["arguments"],
                "response": call_response,
            })

    return {"statusCode": 200, "body": json.dumps(results, indent=2, default=str)}
```

---

## Environment Variable

| Variable | Value | Example |
|----------|-------|---------|
| `MCP_SERVER_URL` | The ALB DNS endpoint for the ECS MCP server | `http://mcp-alb-123456.us-east-1.elb.amazonaws.com` |

---

## Test Events

### List Tools Only
```json
{
  "action": "list_tools"
}
```

### Call a Specific Tool
```json
{
  "action": "call_tool",
  "tool_name": "add",
  "arguments": {"a": 100, "b": 200}
}
```

### Full Test (List + Call All Tools)
```json
{
  "action": "full_test"
}
```

---

## Expected Output (Full Test)

When everything is working, the `full_test` action should return:

```json
{
  "statusCode": 200,
  "body": {
    "initialize": {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "protocolVersion": "2025-03-26",
        "capabilities": {
          "tools": {}
        },
        "serverInfo": {
          "name": "aws-mcp-server",
          "version": "1.0.0"
        }
      }
    },
    "tools_list": {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "tools": [
          {"name": "add", "description": "Add two numbers together..."},
          {"name": "multiply", "description": "Multiply two numbers..."},
          {"name": "uppercase", "description": "Convert a string to uppercase"},
          {"name": "reverse", "description": "Reverse a string"}
        ]
      }
    },
    "tool_calls": [
      {"tool": "add", "arguments": {"a": 10, "b": 20}, "response": {"result": 30}},
      {"tool": "multiply", "arguments": {"a": 7, "b": 6}, "response": {"result": 42}},
      {"tool": "uppercase", "arguments": {"text": "hello mcp"}, "response": {"result": "HELLO MCP"}},
      {"tool": "reverse", "arguments": {"text": "aws lambda"}, "response": {"result": "adbmal swa"}}
    ]
  }
}
```

---

## Key Design Notes

### Why stdlib only (no pip packages)?

The client Lambda uses only Python's built-in `urllib` module:
- **No Lambda Layer** or zip packaging needed
- **Faster cold starts** — no extra dependencies
- **Simpler deployment** — just paste the code into AWS Console inline editor

### Why not use the MCP Python SDK on the client?

For this POC:
- The SDK adds complexity and dependencies
- The JSON-RPC protocol is simple enough to implement directly
- Using raw HTTP shows exactly what's happening under the hood

For **production**, you'd use the official MCP SDK client for proper session handling, retries, and streaming.

---

**Next:** Go to [05-aws-deployment-guide.md](./05-aws-deployment-guide.md) for step-by-step AWS Console deployment.
