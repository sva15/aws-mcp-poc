# Deployment Guide — Private EC2 + Docker

The MCP Server runs as a Docker container on your **private EC2 instance** (`10.132.191.157:8085`).

---

## Deployment Order

```
Step 1: Enable Bedrock Model Access
Step 2: Create IAM Roles
Step 3: Deploy Tool Lambda Functions (x4)
Step 4: Test Tool Lambdas
Step 5: Set Up EC2 Instance (Docker + IAM)
Step 6: Build & Run MCP Server Container on EC2
Step 7: Verify MCP Server Health
Step 8: Deploy Client Lambda
Step 9: Test End-to-End
```

---

## Step 1: Enable Bedrock Model Access

1. **Amazon Bedrock Console** → **Model access** → **Manage model access**
2. Check **Anthropic → Claude 3 Sonnet** (or **Amazon → Nova Lite** for cheaper)
3. **Request model access** → wait for **Access granted**

---

## Step 2: Create IAM Roles

### 2A: Tool Lambda Role

**IAM** → **Roles** → **Create Role** → Lambda → `AWSLambdaBasicExecutionRole`
**Name**: `mcp-tool-lambda-role`

### 2B: EC2 Instance Role (for MCP Server)

The EC2 instance needs permission to list and invoke Lambda functions.

1. **IAM** → **Roles** → **Create Role** → **EC2**
2. **Create inline policy** → JSON:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ListLambdaFunctions",
            "Effect": "Allow",
            "Action": "lambda:ListFunctions",
            "Resource": "*"
        },
        {
            "Sid": "InvokeToolLambdas",
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": "arn:aws:lambda:*:*:function:mcp-tool-*"
        }
    ]
}
```

3. **Policy name**: `mcp-server-tool-access`
4. **Role name**: `mcp-server-ec2-role`
5. **Attach this role** to your EC2 instance:
   - EC2 Console → Select instance → Actions → Security → **Modify IAM role**
   - Select `mcp-server-ec2-role` → **Update IAM role**

### 2C: Client Lambda Role

1. **IAM** → **Roles** → **Create Role** → Lambda → `AWSLambdaBasicExecutionRole`
2. **Create inline policy** → JSON:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "InvokeBedrock",
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream"
            ],
            "Resource": "arn:aws:bedrock:*::foundation-model/*"
        }
    ]
}
```

3. **Role name**: `mcp-client-lambda-role`

> The client Lambda calls MCP Server via HTTP (`10.132.191.157:8085`) — no `lambda:InvokeFunction` needed.

### Security Group

Ensure the EC2 security group allows **inbound port 8085** from the Lambda's VPC/CIDR.

---

## Step 3: Deploy Tool Lambda Functions

Create 4 Lambda functions (Python 3.12, role: `mcp-tool-lambda-role`):

| Lambda Name | Code Source |
|-------------|-----------|
| `mcp-tool-math` | `tool-lambdas/math_tools/lambda_function.py` |
| `mcp-tool-string` | `tool-lambdas/string_tools/lambda_function.py` |
| `mcp-tool-time` | `tool-lambdas/datetime_tools/lambda_function.py` |
| `mcp-tool-utility` | `tool-lambdas/utility_tools/lambda_function.py` |

---

## Step 4: Test Tool Lambdas

Test each with `{"action": "__describe__"}` and one `__call__` per Lambda.

---

## Step 5: Set Up EC2 Instance

### 5A: Install Docker (if not already installed)

SSH into your EC2 instance:

```bash
ssh ec2-user@10.132.191.157
```

Install Docker:

```bash
# Amazon Linux 2
sudo yum update -y
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Log out and back in for group change to take effect
exit
ssh ec2-user@10.132.191.157
```

Verify:

```bash
docker --version
```

### 5B: Verify IAM Role

The EC2 instance must have the `mcp-server-ec2-role` attached (from Step 2B).

```bash
# Check that the instance can list Lambda functions
aws lambda list-functions --region us-east-1 --query 'Functions[?starts_with(FunctionName, `mcp-tool-`)].FunctionName'
```

✅ Should list your `mcp-tool-*` functions.

---

## Step 6: Build & Run MCP Server on EC2

### 6A: Copy Source Code to EC2

From your local machine:

```bash
# Copy the mcp-server folder to EC2
scp -r mcp-server/ ec2-user@10.132.191.157:~/mcp-server/
```

Or clone/download the code directly on EC2.

### 6B: Build the Docker Image

On the EC2 instance:

```bash
cd ~/mcp-server
docker build -t mcp-server .
```

### 6C: Run the Container

```bash
docker run -d \
  --name mcp-server \
  --restart unless-stopped \
  -p 8085:8085 \
  -e AWS_REGION=us-east-1 \
  -e TOOL_PREFIX=mcp-tool- \
  -e CACHE_TTL=300 \
  -e LOG_LEVEL=INFO \
  mcp-server
```

**Flags explained:**
| Flag | Purpose |
|------|---------|
| `-d` | Run in background (detached) |
| `--restart unless-stopped` | Auto-restart on crash or reboot |
| `-p 8085:8085` | Map EC2 port 8085 → container port 8085 |
| `-e AWS_REGION=us-east-1` | Set your region |

### 6D: Check Container Status

```bash
# Is it running?
docker ps

# View logs (follow mode)
docker logs -f mcp-server

# Check health
curl http://localhost:8085/health
```

You should see startup logs like:

```
============================================================
  MCP Server 'aws-mcp-server' v1.0.0 starting
  Endpoint: http://0.0.0.0:8085/mcp
  Health:   http://0.0.0.0:8085/health
============================================================
Running initial tool discovery...
Lambda scan: found 4 functions matching 'mcp-tool-'
  • add                  ← mcp-tool-math              │ Add two numbers together...
  • multiply             ← mcp-tool-math              │ Multiply two numbers...
  ...
DISCOVERY COMPLETE: 14 tools from 4 Lambdas
============================================================
  Server ready to accept connections
============================================================
```

---

## Step 7: Verify MCP Server

### Health Check

```bash
curl http://10.132.191.157:8085/health
```

Expected:
```json
{
    "status": "healthy",
    "server": "aws-mcp-server",
    "tools_discovered": 14,
    "tool_names": ["add", "multiply", "subtract", "divide", "uppercase", ...]
}
```

### Test tools/list

```bash
curl -X POST http://10.132.191.157:8085/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

✅ Should return all 14 tools.

### Test tools/call

```bash
curl -X POST http://10.132.191.157:8085/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"add","arguments":{"a":5,"b":3}}}'
```

✅ Should return `{"result": 8}`.

---

## Step 8: Deploy Client Lambda

1. **Lambda Console** → **Create Function**
2. **Name**: `mcp-client`
3. **Runtime**: Python 3.12
4. **Role**: `mcp-client-lambda-role`
5. Paste code from: `client-lambda/lambda_function.py`
6. **Deploy**

### Configure:

| Setting | Value |
|---------|-------|
| **Timeout** | 120 seconds |
| **Memory** | 256 MB |
| **VPC** | Same VPC as the EC2 instance (so it can reach `10.132.191.157`) |
| **Subnets** | Private subnets that can reach the EC2 |
| **Security Group** | Allow outbound to `10.132.191.157:8085` |

**Environment Variables:**

| Key | Value |
|-----|-------|
| `AWS_REGION` | `us-east-1` |
| `MCP_SERVER_URL` | `http://10.132.191.157:8085/mcp` |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-sonnet-20240229-v1:0` |

> **Important**: The client Lambda MUST be in the same VPC as the EC2 instance (or have network connectivity to `10.132.191.157`).

---

## Step 9: Test End-to-End

See [03-testing-guide.md](./03-testing-guide.md) for the full test suite.

Quick smoke tests on the `mcp-client` Lambda:

```json
{"action": "list_tools"}
```
```json
{"question": "What is 15 multiplied by 27?"}
```
```json
{"question": "Convert 100 Celsius to Fahrenheit"}
```

---

## Useful Docker Commands

```bash
# View live logs
docker logs -f mcp-server

# Restart container
docker restart mcp-server

# Stop and remove
docker stop mcp-server && docker rm mcp-server

# Rebuild and re-run (after code changes)
docker build -t mcp-server . && docker run -d --name mcp-server --restart unless-stopped -p 8085:8085 -e AWS_REGION=us-east-1 -e TOOL_PREFIX=mcp-tool- -e CACHE_TTL=300 mcp-server
```

---

## Resource Cleanup

1. **EC2**: `docker stop mcp-server && docker rm mcp-server && docker rmi mcp-server`
2. **Lambda**: Delete `mcp-tool-math`, `mcp-tool-string`, `mcp-tool-time`, `mcp-tool-utility`, `mcp-client`
3. **IAM**: Delete roles `mcp-server-ec2-role`, `mcp-tool-lambda-role`, `mcp-client-lambda-role`
