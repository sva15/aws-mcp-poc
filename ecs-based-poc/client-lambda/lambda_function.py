"""
MCP Client Lambda — Bedrock-Powered AI Assistant.

This Lambda is the bridge between the user, Amazon Bedrock (AI model),
and the MCP Server (tool registry + executor).

Architecture:
  User → Client Lambda → Bedrock (AI) → Client Lambda → MCP Server → Tool Lambda

Why format conversion IS required:
  MCP and Bedrock are two completely different protocols.
  MCP defines tools as: {"name", "description", "inputSchema": {JSON Schema}}
  Bedrock expects:      {"toolSpec": {"name", "description", "inputSchema": {"json": {JSON Schema}}}}
  The Client Lambda converts between these two formats.
  This is NOT optional — Bedrock cannot read MCP format directly.

How Bedrock selects the right tool:
  1. We send the user's question + ALL available tools to Bedrock
  2. Bedrock reads every tool's name, description, and inputSchema
  3. The AI model matches the user's intent against tool descriptions
  4. It generates a structured "tool_use" response with the tool name + arguments
  5. We execute the tool via MCP Server and send the result back
  6. Bedrock generates a final human-readable answer

Official Bedrock API: converse (supports tool use natively)
Official MCP SDK: We use raw HTTP here (JSON-RPC) since it's the standard protocol
  and avoids needing the MCP SDK package in the Lambda deployment.
"""

import os
import json
import logging
import urllib.request
import urllib.error

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ─── Configuration ───────────────────────────────────────────────

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# URL of the MCP Server running on ECS behind an ALB
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server-alb.example.com/mcp")

# Bedrock model to use for AI reasoning
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-sonnet-20240229-v1:0"
)

# Maximum tool use iterations (safety limit)
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "5"))

# AWS clients (created once, reused across warm invocations)
bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)


# ─── MCP Server Communication (Streamable HTTP) ─────────────────
# The MCP protocol uses JSON-RPC 2.0 over HTTP POST.
# We use Python's built-in urllib (no external dependencies).

def send_mcp_request(method: str, params: dict = None) -> dict:
    """
    Send a JSON-RPC 2.0 request to the MCP Server.

    This is speaking the MCP protocol directly — JSON-RPC over HTTP.
    The MCP Server running on ECS listens on /mcp for these requests.

    Args:
        method: MCP method name (e.g., "tools/list", "tools/call")
        params: Optional parameters dict

    Returns:
        The JSON-RPC response dict (contains "result" or "error")

    How this works:
        1. Build JSON-RPC request body
        2. POST to MCP Server's /mcp endpoint
        3. Parse JSON-RPC response
        4. Return the result
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params

    logger.info(f"[MCP] → {method} | params: {json.dumps(params or {})[:200]}")

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        MCP_SERVER_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = resp.read().decode("utf-8")
            result = json.loads(response_body)
            logger.info(f"[MCP] ← {method} | response: {response_body[:300]}")
            return result

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"[MCP] ✗ HTTP {e.code} from MCP Server: {body[:200]}")
        return {"error": {"code": e.code, "message": f"HTTP {e.code}: {body[:200]}"}}

    except urllib.error.URLError as e:
        logger.error(f"[MCP] ✗ Cannot reach MCP Server at {MCP_SERVER_URL}: {e.reason}")
        return {"error": {"code": -1, "message": f"Cannot reach MCP Server: {e.reason}"}}

    except Exception as e:
        logger.error(f"[MCP] ✗ Unexpected error: {e}")
        return {"error": {"code": -1, "message": str(e)}}


def get_available_tools() -> list[dict]:
    """
    Get all available tools from the MCP Server.

    Sends: {"method": "tools/list"}
    Returns: List of tool definitions with name, description, inputSchema
    """
    response = send_mcp_request("tools/list")

    if "error" in response:
        logger.error(f"[MCP] Failed to list tools: {response['error']}")
        return []

    tools = response.get("result", {}).get("tools", [])
    tool_names = [t["name"] for t in tools]
    logger.info(f"[MCP] Available tools ({len(tools)}): {tool_names}")
    return tools


def execute_tool(tool_name: str, arguments: dict) -> dict:
    """
    Execute a tool via the MCP Server.

    Sends: {"method": "tools/call", "params": {"name": "add", "arguments": {...}}}
    Returns: The tool's result dict
    """
    response = send_mcp_request("tools/call", {
        "name": tool_name,
        "arguments": arguments,
    })

    if "error" in response:
        logger.error(f"[MCP] Tool execution failed: {response['error']}")
        return {"error": response["error"].get("message", "Tool execution failed")}

    # Extract result from MCP content format
    result = response.get("result", {})
    if "content" in result:
        for block in result["content"]:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except json.JSONDecodeError:
                    return {"result": block["text"]}

    return result


# ─── Bedrock Format Conversion ───────────────────────────────────
# MCP and Bedrock define tool schemas differently.
# This conversion is REQUIRED — they are two different protocols.

def convert_mcp_tools_to_bedrock_format(mcp_tools: list[dict]) -> list[dict]:
    """
    Convert MCP tool definitions → Bedrock tool specifications.

    Why this conversion exists:
        MCP format:     {"name", "description", "inputSchema": {JSON Schema}}
        Bedrock format: {"toolSpec": {"name", "description", "inputSchema": {"json": {JSON Schema}}}}

    The key difference is Bedrock wraps the JSON Schema inside:
        toolSpec → inputSchema → json → {actual schema}

    This is NOT optional. Bedrock's converse API requires this exact structure.
    See: https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html
    """
    bedrock_tools = []

    for tool in mcp_tools:
        # Get inputSchema — handle both naming conventions
        input_schema = tool.get("inputSchema", tool.get("input_schema", {}))

        bedrock_tool = {
            "toolSpec": {
                "name": tool["name"],
                "description": tool.get("description", f"Tool: {tool['name']}"),
                "inputSchema": {
                    "json": input_schema  # ← This nesting is the key difference
                },
            }
        }
        bedrock_tools.append(bedrock_tool)

    logger.info(
        f"[CONVERT] Converted {len(bedrock_tools)} tools: "
        f"MCP format → Bedrock format | "
        f"names: {[t['toolSpec']['name'] for t in bedrock_tools]}"
    )

    return bedrock_tools


# ─── Bedrock Integration ─────────────────────────────────────────

def call_bedrock(messages: list, tools_config: list) -> dict:
    """
    Call the Bedrock converse API with the user's question and available tools.

    How Bedrock tool use works:
        1. We send: user message + tool definitions
        2. Bedrock AI reads the question and all tool descriptions
        3. If a tool matches the intent → stopReason: "tool_use"
        4. If no tool is needed → stopReason: "end_turn" (direct answer)

    The AI model is trained on millions of function-calling examples.
    It matches the user's intent against tool descriptions to decide:
        - Which tool to call (by matching description to intent)
        - What arguments to pass (by parsing the question against inputSchema)
        - Whether to call any tool at all (answers directly if no tool fits)
    """
    request_body = {
        "modelId": BEDROCK_MODEL_ID,
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": 1024,
            "temperature": 0.0,  # Deterministic for tool calling
        },
        "system": [
            {
                "text": (
                    "You are a helpful assistant with access to tools. "
                    "When the user asks a question that can be answered using a tool, "
                    "use the appropriate tool. Always prefer using tools when applicable. "
                    "After getting the tool result, provide a clear natural language answer. "
                    "If no tool is relevant, answer directly from your knowledge."
                )
            }
        ],
    }

    if tools_config:
        request_body["toolConfig"] = {"tools": tools_config}

    logger.info(
        f"[BEDROCK] → converse | model: {BEDROCK_MODEL_ID} | "
        f"messages: {len(messages)} | tools: {len(tools_config)}"
    )

    response = bedrock_client.converse(**request_body)

    stop_reason = response.get("stopReason", "unknown")
    logger.info(f"[BEDROCK] ← stopReason: {stop_reason}")

    return response


# ─── Orchestration Loop ──────────────────────────────────────────
# This is the core of the client: the tool use conversation loop.

def process_question(question: str) -> dict:
    """
    Full orchestration: question → tools → Bedrock → tool calls → answer.

    The loop works like this:
        1. Get tools from MCP Server
        2. Convert to Bedrock format
        3. Send question + tools to Bedrock
        4. If Bedrock says "tool_use" → execute tool via MCP → send result back
        5. Repeat until Bedrock says "end_turn" (final answer)

    Why a loop?
        Bedrock might need MULTIPLE tools to answer one question.
        Example: "Add 50 and 75, then reverse the result"
            → Iteration 1: call add(50, 75) → 125
            → Iteration 2: call reverse("125") → "521"
            → Iteration 3: final answer
    """
    logger.info("=" * 60)
    logger.info(f"[PROCESS] Starting | Question: '{question}'")
    logger.info("=" * 60)

    # ── Step 1: Get available tools from MCP Server ──────────────
    logger.info("[STEP 1] Getting available tools from MCP Server...")
    mcp_tools = get_available_tools()

    if not mcp_tools:
        logger.warning("[STEP 1] No tools available! Asking Bedrock without tools.")

    # ── Step 2: Convert to Bedrock format ────────────────────────
    logger.info("[STEP 2] Converting MCP tools → Bedrock format...")
    bedrock_tools = convert_mcp_tools_to_bedrock_format(mcp_tools)

    # ── Step 3: Start the conversation loop ──────────────────────
    messages = [
        {"role": "user", "content": [{"text": question}]}
    ]

    tools_used = []

    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info(f"[STEP 3] Bedrock call — iteration {iteration}/{MAX_ITERATIONS}")

        # Call Bedrock
        response = call_bedrock(messages, bedrock_tools)

        stop_reason = response.get("stopReason", "")
        output_message = response.get("output", {}).get("message", {})
        output_content = output_message.get("content", [])

        # Add assistant's response to conversation history
        messages.append({"role": "assistant", "content": output_content})

        # ── Bedrock wants to use a tool ──────────────────────────
        if stop_reason == "tool_use":
            tool_results = []

            for block in output_content:
                if "toolUse" in block:
                    tool_use = block["toolUse"]
                    tool_name = tool_use["name"]
                    tool_input = tool_use["input"]
                    tool_use_id = tool_use["toolUseId"]

                    logger.info(
                        f"[STEP 4] Bedrock wants tool: '{tool_name}' "
                        f"with args: {json.dumps(tool_input)}"
                    )

                    # Execute via MCP Server
                    logger.info(f"[STEP 5] Executing '{tool_name}' via MCP Server...")
                    tool_result = execute_tool(tool_name, tool_input)

                    logger.info(
                        f"[STEP 5] Tool '{tool_name}' result: "
                        f"{json.dumps(tool_result)[:200]}"
                    )

                    tools_used.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "output": tool_result,
                    })

                    # Format result for Bedrock
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": tool_result}],
                        }
                    })

            # Send tool results back to Bedrock
            logger.info(f"[STEP 6] Sending {len(tool_results)} tool result(s) back to Bedrock...")
            messages.append({"role": "user", "content": tool_results})

        # ── Bedrock gives a final text answer ────────────────────
        elif stop_reason == "end_turn":
            final_answer = ""
            for block in output_content:
                if "text" in block:
                    final_answer += block["text"]

            logger.info("=" * 60)
            logger.info(f"[DONE] Final answer: {final_answer[:300]}")
            logger.info(f"[DONE] Tools used: {[t['tool'] for t in tools_used]}")
            logger.info(f"[DONE] Iterations: {iteration}")
            logger.info("=" * 60)

            return {
                "answer": final_answer,
                "tools_used": tools_used,
                "tools_available": [t["name"] for t in mcp_tools],
                "model": BEDROCK_MODEL_ID,
                "iterations": iteration,
            }

        else:
            logger.warning(f"[UNEXPECTED] Bedrock stopReason: '{stop_reason}'")
            return {
                "answer": f"Unexpected response from model (stopReason: {stop_reason})",
                "tools_used": tools_used,
            }

    # Safety: max iterations reached
    logger.warning(f"[LIMIT] Max iterations ({MAX_ITERATIONS}) reached")
    return {
        "answer": "Maximum tool use iterations reached. Partial result available.",
        "tools_used": tools_used,
    }


# ─── Lambda Entry Point ──────────────────────────────────────────

def lambda_handler(event, context):
    """
    Lambda handler. Supports three input modes:

    Mode 1 — Ask a question (Bedrock + MCP):
        {"question": "What is 15 multiplied by 27?"}

    Mode 2 — List tools (debug):
        {"action": "list_tools"}

    Mode 3 — Direct tool call (bypass Bedrock):
        {"action": "call_tool", "tool_name": "add", "arguments": {"a": 5, "b": 3}}
    """
    logger.info(f"[LAMBDA] Invoked with: {json.dumps(event)[:500]}")

    action = event.get("action", "ask")

    try:
        if action == "list_tools":
            tools = get_available_tools()
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "tools": tools,
                    "count": len(tools),
                    "mcp_server_url": MCP_SERVER_URL,
                }, indent=2),
            }

        elif action == "call_tool":
            tool_name = event.get("tool_name", "")
            arguments = event.get("arguments", {})
            if not tool_name:
                return {"statusCode": 400, "body": json.dumps({"error": "tool_name is required"})}
            result = execute_tool(tool_name, arguments)
            return {
                "statusCode": 200,
                "body": json.dumps({"tool": tool_name, "result": result}, indent=2),
            }

        else:
            question = event.get("question", "")
            if not question:
                return {"statusCode": 400, "body": json.dumps({"error": "question is required"})}
            result = process_question(question)
            return {
                "statusCode": 200,
                "body": json.dumps(result, indent=2, default=str),
            }

    except Exception as e:
        logger.error(f"[LAMBDA] Error: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
