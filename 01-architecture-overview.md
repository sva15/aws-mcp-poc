# MCP Server POC on AWS — Architecture Overview & Design

## 1. What is MCP (Model Context Protocol)?

MCP is an **open standard** (created by Anthropic) that defines how AI applications communicate with external tools, data sources, and services. Think of it as a **universal adapter** between AI models and the real world.

**Key Concepts:**

| Concept | Description |
|---------|-------------|
| **MCP Server** | A process that exposes "tools" and "resources" via a standardized JSON-RPC protocol |
| **MCP Client** | Any application that connects to an MCP server to discover and invoke tools |
| **Tool** | A callable function with a defined name, description, and input schema |
| **Transport** | The communication layer — can be `stdio`, `SSE (Server-Sent Events)`, or `Streamable HTTP` |

For this POC, we use **Streamable HTTP transport** — the MCP server runs as an HTTP service, and clients call it over HTTP POST requests.

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          AWS CLOUD                                   │
│                                                                      │
│  ┌─────────────────┐         ┌──────────────────────────────┐        │
│  │  CLIENT LAMBDA   │  HTTP   │  ECS FARGATE CLUSTER         │        │
│  │                  │────────▶│  ┌──────────────────────┐    │        │
│  │  (MCP Client)    │  POST   │  │  MCP SERVER           │    │        │
│  │                  │◀────────│  │  (Python FastAPI)     │    │        │
│  │  Discovers tools │         │  │                      │    │        │
│  │  and invokes them│         │  │  /mcp  endpoint      │    │        │
│  └─────────────────┘         │  │  - list tools        │    │        │
│                               │  │  - call tools        │    │        │
│                               │  └──────────┬───────────┘    │        │
│                               │             │                │        │
│                               └─────────────┼────────────────┘        │
│                                             │                         │
│                                             │ invoke                  │
│                                             ▼                         │
│                    ┌────────────────────────────────────────┐         │
│                    │        TOOL LAMBDA FUNCTIONS            │         │
│                    │                                        │         │
│                    │  ┌──────────────┐  ┌──────────────┐   │         │
│                    │  │ math-tools   │  │ string-tools │   │         │
│                    │  │              │  │              │   │         │
│                    │  │ - add        │  │ - uppercase  │   │         │
│                    │  │ - multiply   │  │ - reverse    │   │         │
│                    │  └──────────────┘  └──────────────┘   │         │
│                    │                                        │         │
│                    └────────────────────────────────────────┘         │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Breakdown

### Component 1: MCP Server (Runs on ECS Fargate)

| Property | Value |
|----------|-------|
| **Runtime** | Python 3.12 |
| **Framework** | FastAPI + official `mcp` Python SDK |
| **Transport** | Streamable HTTP (`/mcp` endpoint) |
| **Container** | Docker image pushed to ECR |
| **Port** | 8000 |

**Responsibilities:**
1. On startup, reads a **tool registry** (environment variable) that lists tool Lambda function ARNs
2. On `tools/list` request — queries each tool Lambda with a `__describe__` action to get tool metadata
3. On `tools/call` request — invokes the correct tool Lambda with the input arguments
4. Returns results back to the MCP client

### Component 2: Tool Lambda Functions

Each tool Lambda is a **standalone Lambda function** that:
1. Responds to a `__describe__` action with its tool definitions (name, description, input schema)
2. Responds to a `__call__` action by executing the requested tool and returning the result

**POC creates two tool Lambdas:**

| Lambda Name | Tools Provided |
|-------------|---------------|
| `mcp-tool-math` | `add(a, b)` → returns sum, `multiply(a, b)` → returns product |
| `mcp-tool-string` | `uppercase(text)` → returns uppercased text, `reverse(text)` → returns reversed text |

### Component 3: Client Lambda Function

A Lambda function that acts as the **MCP Client**:
1. Connects to the MCP server's HTTP endpoint
2. Calls `tools/list` to discover all available tools
3. Calls `tools/call` to invoke a specific tool
4. Returns the results

---

## 4. Communication Flow

```
Step 1: Client Lambda → POST /mcp → MCP Server
        Body: {"jsonrpc": "2.0", "method": "initialize", ...}
        Response: Server capabilities

Step 2: Client Lambda → POST /mcp → MCP Server
        Body: {"jsonrpc": "2.0", "method": "tools/list"}
        
        MCP Server internally:
          → Invokes mcp-tool-math Lambda with {"action": "__describe__"}
          → Invokes mcp-tool-string Lambda with {"action": "__describe__"}
          → Collects tool definitions
        
        Response: List of 4 tools (add, multiply, uppercase, reverse)

Step 3: Client Lambda → POST /mcp → MCP Server
        Body: {"jsonrpc": "2.0", "method": "tools/call", 
               "params": {"name": "add", "arguments": {"a": 5, "b": 3}}}
        
        MCP Server internally:
          → Invokes mcp-tool-math Lambda with {"action": "__call__", "tool": "add", "arguments": {"a": 5, "b": 3}}
        
        Response: {"result": 8}
```

---

## 5. AWS Services Used

| Service | Purpose |
|---------|---------|
| **Amazon ECS (Fargate)** | Runs the MCP server container |
| **Amazon ECR** | Stores the Docker image for MCP server |
| **AWS Lambda** (x3) | Client Lambda + 2 Tool Lambdas |
| **CloudWatch Logs** | Logs from all components |
| **IAM** | Roles and permissions |
| **VPC** | Networking (ECS tasks run in a VPC) |
| **ALB (Application Load Balancer)** | Exposes ECS service via HTTP endpoint |

---

## 6. IAM Permissions Required

### MCP Server (ECS Task Role)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": [
        "arn:aws:lambda:REGION:ACCOUNT:function:mcp-tool-*"
      ]
    }
  ]
}
```

### Client Lambda (Execution Role)
- No special permissions needed beyond basic Lambda execution
- The client calls the MCP server via HTTP (through ALB), not through AWS API

### Tool Lambdas (Execution Role)
- Basic Lambda execution role (CloudWatch Logs only)

---

## 7. Networking Design

```
Internet/Internal
       │
       ▼
┌─────────────────┐
│  ALB             │   Port 80 → Target Group Port 8000
│  (Internal)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ECS Fargate     │   Runs MCP Server container
│  Service         │   Port 8000
│  (Private Subnet)│
└─────────────────┘
```

- ALB is **internal** (no public access needed for POC)
- Client Lambda must be in the **same VPC** or have access to the ALB
- For simplicity in POC: use a **public ALB** so Client Lambda doesn't need VPC config

> **Production Note:** In production, use an internal ALB + VPC Lambda or AWS PrivateLink.

---

## 8. File Structure (What You'll Create)

```
MCP-POC-AWS/
├── 01-architecture-overview.md          ← This document
├── 02-mcp-server-code.md                ← MCP server Python code + Dockerfile
├── 03-tool-lambda-functions.md          ← Tool Lambda code
├── 04-client-lambda-code.md             ← Client Lambda code
├── 05-aws-deployment-guide.md           ← Step-by-step AWS Console guide
├── 06-ecs-vs-lambda-comparison.md       ← ECS vs Lambda evaluation
├── 07-testing-guide.md                  ← Testing & verification
├── 08-production-readiness.md           ← Steps to make it production-ready
│
├── mcp-server/                          ← MCP Server source code
│   ├── server.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── tool-lambdas/
│   ├── math_tools/
│   │   └── lambda_function.py
│   └── string_tools/
│       └── lambda_function.py
│
└── client-lambda/
    └── lambda_function.py
```

---

## 9. Quick Start Summary

| Step | Action | Document |
|------|--------|----------|
| 1 | Understand the architecture | `01-architecture-overview.md` |
| 2 | Create MCP server code & Docker image | `02-mcp-server-code.md` |
| 3 | Create tool Lambda functions | `03-tool-lambda-functions.md` |
| 4 | Create client Lambda function | `04-client-lambda-code.md` |
| 5 | Deploy everything via AWS Console | `05-aws-deployment-guide.md` |
| 6 | Test the entire flow | `07-testing-guide.md` |
| 7 | Compare ECS vs Lambda hosting | `06-ecs-vs-lambda-comparison.md` |
| 8 | Plan production migration | `08-production-readiness.md` |

---

**Next:** Go to [02-mcp-server-code.md](./02-mcp-server-code.md) for the MCP server implementation.
