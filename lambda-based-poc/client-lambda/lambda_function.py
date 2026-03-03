"""
MCP Client Lambda — Bedrock-Powered
Takes a user question, uses Bedrock to decide which tool to call,
calls the MCP server, and returns an intelligent answer.
"""

import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MCP_SERVER_FUNCTION = os.environ.get("MCP_SERVER_FUNCTION", "mcp-server")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")

lambda_client = boto3.client("lambda", region_name=AWS_REGION)
bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)


# ──────────────────────────────────────────────
# MCP Server Communication
# ──────────────────────────────────────────────

def call_mcp_server(method, params=None):
    """Send a JSON-RPC request to the MCP Server Lambda."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params

    logger.info(f"Calling MCP Server: method={method}")

    response = lambda_client.invoke(
        FunctionName=MCP_SERVER_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )

    result = json.loads(response["Payload"].read().decode())

    # Unwrap Lambda response
    if isinstance(result, dict) and "body" in result:
        result = json.loads(result["body"]) if isinstance(result["body"], str) else result["body"]

    logger.info(f"MCP Server response: {json.dumps(result)[:500]}")
    return result


def get_available_tools():
    """Get all available tools from MCP Server."""
    response = call_mcp_server("tools/list")
    tools = response.get("result", {}).get("tools", [])
    logger.info(f"Available tools: {[t['name'] for t in tools]}")
    return tools


def execute_tool(tool_name, arguments):
    """Execute a tool via MCP Server."""
    response = call_mcp_server("tools/call", {
        "name": tool_name,
        "arguments": arguments,
    })

    # Extract the result from the MCP response
    result = response.get("result", {})
    if "content" in result:
        for content_block in result["content"]:
            if content_block.get("type") == "text":
                try:
                    return json.loads(content_block["text"])
                except json.JSONDecodeError:
                    return {"result": content_block["text"]}

    if "error" in response:
        return {"error": response["error"].get("message", "Unknown error")}

    return result


# ──────────────────────────────────────────────
# Bedrock Integration
# ──────────────────────────────────────────────

def mcp_tools_to_bedrock_format(mcp_tools):
    """
    Convert MCP tool definitions to Bedrock tool specification format.
    
    MCP format:
    {
        "name": "add",
        "description": "Add two numbers",
        "inputSchema": {"type": "object", "properties": {...}, "required": [...]}
    }
    
    Bedrock format:
    {
        "toolSpec": {
            "name": "add",
            "description": "Add two numbers",
            "inputSchema": {
                "json": {"type": "object", "properties": {...}, "required": [...]}
            }
        }
    }
    """
    bedrock_tools = []
    for tool in mcp_tools:
        input_schema = tool.get("inputSchema", tool.get("input_schema", {}))

        bedrock_tool = {
            "toolSpec": {
                "name": tool["name"],
                "description": tool.get("description", f"Tool: {tool['name']}"),
                "inputSchema": {
                    "json": input_schema
                }
            }
        }
        bedrock_tools.append(bedrock_tool)

    return bedrock_tools


def ask_bedrock(question, tools_config, messages=None):
    """
    Send a request to Bedrock with the user's question and available tools.
    Returns the model's response.
    """
    if messages is None:
        messages = [
            {
                "role": "user",
                "content": [{"text": question}]
            }
        ]

    request_body = {
        "modelId": BEDROCK_MODEL_ID,
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": 1024,
            "temperature": 0.0,
        },
        "system": [
            {
                "text": (
                    "You are a helpful assistant with access to tools. "
                    "When the user asks a question that can be answered using one of "
                    "your available tools, use the appropriate tool. "
                    "Always use tools when they are relevant to the question. "
                    "After getting the tool result, provide a clear, natural language answer."
                )
            }
        ],
    }

    if tools_config:
        request_body["toolConfig"] = {
            "tools": tools_config
        }

    logger.info(f"Calling Bedrock model: {BEDROCK_MODEL_ID}")
    logger.info(f"Tools provided: {[t['toolSpec']['name'] for t in tools_config]}")

    response = bedrock_client.converse(**request_body)

    return response


# ──────────────────────────────────────────────
# Orchestration Loop (Tool Use Cycle)
# ──────────────────────────────────────────────

def process_question(question):
    """
    Full orchestration:
    1. Get tools from MCP Server
    2. Ask Bedrock with question + tools
    3. If Bedrock wants to use a tool → execute it via MCP → send result back
    4. Repeat until Bedrock gives a final text answer
    """
    logger.info(f"Processing question: {question}")

    # Step 1: Get available tools
    mcp_tools = get_available_tools()
    bedrock_tools = mcp_tools_to_bedrock_format(mcp_tools)

    logger.info(f"Converted {len(bedrock_tools)} tools to Bedrock format")

    # Step 2: Initial Bedrock call
    messages = [
        {
            "role": "user",
            "content": [{"text": question}]
        }
    ]

    max_iterations = 5  # Safety limit for tool use loops
    tool_calls_made = []

    for iteration in range(max_iterations):
        logger.info(f"Bedrock call iteration {iteration + 1}")

        response = ask_bedrock(question, bedrock_tools, messages)

        stop_reason = response.get("stopReason", "")
        output_message = response.get("output", {}).get("message", {})
        output_content = output_message.get("content", [])

        logger.info(f"Bedrock stop reason: {stop_reason}")

        # Add assistant's response to conversation
        messages.append({"role": "assistant", "content": output_content})

        # If Bedrock wants to use a tool
        if stop_reason == "tool_use":
            tool_results = []

            for content_block in output_content:
                if "toolUse" in content_block:
                    tool_use = content_block["toolUse"]
                    tool_name = tool_use["name"]
                    tool_input = tool_use["input"]
                    tool_use_id = tool_use["toolUseId"]

                    logger.info(f"Bedrock wants to call: {tool_name}({tool_input})")

                    # Step 3: Execute the tool via MCP Server
                    tool_result = execute_tool(tool_name, tool_input)
                    logger.info(f"Tool result: {tool_result}")

                    tool_calls_made.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "output": tool_result,
                    })

                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": tool_result}],
                        }
                    })

            # Send tool results back to Bedrock
            messages.append({"role": "user", "content": tool_results})

        # If Bedrock gives a final text answer
        elif stop_reason == "end_turn":
            # Extract the text answer
            final_answer = ""
            for content_block in output_content:
                if "text" in content_block:
                    final_answer += content_block["text"]

            logger.info(f"Final answer: {final_answer}")

            return {
                "answer": final_answer,
                "tools_used": tool_calls_made,
                "tools_available": [t["name"] for t in mcp_tools],
                "model": BEDROCK_MODEL_ID,
                "iterations": iteration + 1,
            }

        else:
            # Unexpected stop reason
            return {
                "answer": f"Unexpected response from model (stop_reason: {stop_reason})",
                "tools_used": tool_calls_made,
                "raw_response": output_content,
            }

    return {
        "answer": "Maximum tool use iterations reached",
        "tools_used": tool_calls_made,
    }


# ──────────────────────────────────────────────
# Lambda Entry Point
# ──────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Lambda handler.
    
    Input event formats:
    
    1. Simple question:
       {"question": "What is 15 multiplied by 27?"}
    
    2. List tools only:
       {"action": "list_tools"}
    
    3. Direct tool call (bypass Bedrock):
       {"action": "call_tool", "tool_name": "add", "arguments": {"a": 5, "b": 3}}
    """
    logger.info(f"Client Lambda invoked: {json.dumps(event)[:500]}")

    action = event.get("action", "ask")

    try:
        if action == "list_tools":
            # Just list available tools
            mcp_tools = get_available_tools()
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "tools": mcp_tools,
                    "count": len(mcp_tools),
                }, indent=2)
            }

        elif action == "call_tool":
            # Direct tool call (bypass Bedrock)
            tool_name = event.get("tool_name", "")
            arguments = event.get("arguments", {})
            result = execute_tool(tool_name, arguments)
            return {
                "statusCode": 200,
                "body": json.dumps({"tool": tool_name, "result": result}, indent=2)
            }

        else:
            # Ask a question (uses Bedrock)
            question = event.get("question", "")
            if not question:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "No question provided"})
                }

            result = process_question(question)
            return {
                "statusCode": 200,
                "body": json.dumps(result, indent=2, default=str)
            }

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
