# Deployment Guide — Cloud-Agnostic MCP Server

---

## Architecture

```
Client (any) → MCP Server (container, 10.132.191.157:8085)
                    ↓ HTTP
               Tools ALB (path-based routing)
               ├── /registry     → Tool Registry Lambda
               ├── /tools/math   → Math Tools Lambda
               ├── /tools/string → String Tools Lambda
               ├── /tools/time   → DateTime Tools Lambda
               └── /tools/utility → Utility Tools Lambda
```

## Deployment Order

```
Step 1: Enable Bedrock Model Access
Step 2: Create IAM Roles
Step 3: Deploy Tool Lambda Functions (x4)
Step 4: Deploy Tool Registry Lambda
Step 5: Create ALB with Path-Based Routing
Step 6: Test ALB Endpoints (registry + tools)
Step 7: Build & Run MCP Server Container on EC2
Step 8: Deploy Client Lambda
Step 9: Test End-to-End
```

---

## Step 1: Enable Bedrock Model Access

1. **Bedrock Console** → **Model access** → **Manage model access**
2. Enable **Anthropic → Claude 3 Sonnet** (or **Amazon → Nova Lite**)

---

## Step 2: Create IAM Roles

### 2A: Tool Lambda Role (for all tool Lambdas + registry)

**IAM** → **Roles** → **Create** → Lambda → `AWSLambdaBasicExecutionRole`
**Name**: `mcp-tool-lambda-role`

### 2B: EC2 Instance Role (for MCP Server)

The EC2 instance does NOT need Lambda permissions anymore (cloud-agnostic!).
It only needs basic EC2 permissions if not already assigned.

### 2C: Client Lambda Role

1. **Create Role** → Lambda → `AWSLambdaBasicExecutionRole`
2. **Inline policy** for Bedrock:

```json
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        "Resource": "arn:aws:bedrock:*::foundation-model/*"
    }]
}
```

3. **Name**: `mcp-client-lambda-role`

---

## Step 3: Deploy Tool Lambda Functions

Create 4 Lambdas (Python 3.12, role: `mcp-tool-lambda-role`, timeout: 30s):

| Lambda Name | Code Source |
|-------------|-----------|
| `mcp-tool-math` | `tool-lambdas/math_tools/lambda_function.py` |
| `mcp-tool-string` | `tool-lambdas/string_tools/lambda_function.py` |
| `mcp-tool-time` | `tool-lambdas/datetime_tools/lambda_function.py` |
| `mcp-tool-utility` | `tool-lambdas/utility_tools/lambda_function.py` |

Test each with `{"action":"__describe__"}` (direct invocation, still works).

---

## Step 4: Deploy Tool Registry Lambda

| Setting | Value |
|---------|-------|
| **Name** | `mcp-tool-registry` |
| **Runtime** | Python 3.12 |
| **Role** | `mcp-tool-lambda-role` |
| **Timeout** | 30 seconds |
| **Code** | `tool-registry/lambda_function.py` |

**Environment Variable:**

| Key | Value |
|-----|-------|
| `ALB_BASE_URL` | `http://<TOOLS-ALB-DNS>` (set after creating ALB in Step 5) |

Test: `{"action":"list"}` → should return 4 providers, 14 tools.

---

## Step 5: Create ALB with Path-Based Routing

### 5A: Create Target Groups (Lambda type)

Create 5 target groups, each with target type **Lambda**:

| Target Group Name | Lambda Target |
|-------------------|--------------|
| `tg-registry` | `mcp-tool-registry` |
| `tg-math` | `mcp-tool-math` |
| `tg-string` | `mcp-tool-string` |
| `tg-time` | `mcp-tool-time` |
| `tg-utility` | `mcp-tool-utility` |

For each: **EC2** → **Target Groups** → **Create** → Target type: **Lambda function** → Select Lambda → **Create**.

> **Important**: When you register a Lambda as a target, AWS automatically adds the required `elasticloadbalancing:invoke` permission to the Lambda's resource policy.

### 5B: Create Application Load Balancer

1. **EC2** → **Load Balancers** → **Create** → **Application Load Balancer**
2. **Name**: `tools-alb`
3. **Scheme**: Internal (same VPC as EC2 + client Lambda)
4. **Listeners**: HTTP Port 80
5. **VPC**: Select your VPC and at least 2 subnets
6. **Security group**: Allow inbound port 80 from 10.0.0.0/8 (or your VPC CIDR)

### 5C: Configure Listener Rules (Path-Based Routing)

On the HTTP:80 listener, add rules in this order:

| Priority | Condition | Action |
|----------|-----------|--------|
| 1 | Path is `/registry` | Forward to `tg-registry` |
| 2 | Path is `/tools/math` | Forward to `tg-math` |
| 3 | Path is `/tools/string` | Forward to `tg-string` |
| 4 | Path is `/tools/time` | Forward to `tg-time` |
| 5 | Path is `/tools/utility` | Forward to `tg-utility` |
| Default | — | Return 404 |

### 5D: Update Registry's ALB_BASE_URL

After the ALB is created, copy the **DNS name** (e.g., `tools-alb-123456.us-east-1.elb.amazonaws.com`).

Update the Registry Lambda's environment variable:

| Key | Value |
|-----|-------|
| `ALB_BASE_URL` | `http://tools-alb-123456.us-east-1.elb.amazonaws.com` |

---

## Step 6: Test ALB Endpoints

### Test Registry via ALB

```bash
curl -X POST http://<TOOLS-ALB-DNS>/registry \
  -H "Content-Type: application/json" \
  -d '{"action":"list"}'
```

✅ Should return 4 providers, 14 tools with correct ALB URLs.

### Test a Tool via ALB

```bash
curl -X POST http://<TOOLS-ALB-DNS>/tools/math \
  -H "Content-Type: application/json" \
  -d '{"action":"__call__","tool":"add","arguments":{"a":5,"b":3}}'
```

✅ Should return `{"result":8,"expression":"5 + 3 = 8"}`

---

## Step 7: Build & Run MCP Server on EC2

### Copy Updated Code

```bash
scp -r mcp-server/ ec2-user@10.132.191.157:~/mcp-server/
```

### Build & Run

```bash
ssh ec2-user@10.132.191.157

cd ~/mcp-server
docker build -t mcp-server .

docker run -d \
  --name mcp-server \
  --restart unless-stopped \
  -p 8085:8085 \
  -e REGISTRY_URL=http://<TOOLS-ALB-DNS>/registry \
  -e CACHE_TTL_SECONDS=300 \
  -e LOG_LEVEL=INFO \
  mcp-server
```

> Replace `<TOOLS-ALB-DNS>` with your ALB DNS name.

### Verify

```bash
curl http://10.132.191.157:8085/health

curl -X POST http://10.132.191.157:8085/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## Step 8: Deploy Client Lambda

Same as before — see `client-lambda/lambda_function.py`.

| Setting | Value |
|---------|-------|
| **Name** | `mcp-client` |
| **Timeout** | 120 seconds |
| **Memory** | 256 MB |
| **VPC** | Same as EC2 + ALB |

**Env vars:**

| Key | Value |
|-----|-------|
| `MCP_SERVER_URL` | `http://10.132.191.157:8085/mcp` |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-sonnet-20240229-v1:0` |

---

## Step 9: Test End-to-End

```json
{"action": "list_tools"}
{"question": "What is 15 multiplied by 27?"}
{"question": "Convert 100 Celsius to Fahrenheit"}
{"question": "What is today's date?"}
```

---

## Adding a New Tool

1. Write a new Lambda with `__describe__` / `__call__` protocol + ALB wrapper
2. Deploy the Lambda
3. Create a target group → register Lambda
4. Add ALB listener rule: `/tools/new-tool` → target group
5. Register with registry:

```bash
curl -X POST http://<TOOLS-ALB-DNS>/registry \
  -H "Content-Type: application/json" \
  -d '{"action":"register","provider":{"name":"new-tool","url":"http://<ALB>/tools/new-tool","tools":[{"name":"greet","description":"...","input_schema":{...}}]}}'
```

6. Wait for MCP server cache to expire (5 min) or restart the container

---

## Cleanup

1. **EC2**: `docker stop mcp-server && docker rm mcp-server`
2. **ALB**: Delete load balancer → delete target groups
3. **Lambda**: Delete all `mcp-tool-*`, `mcp-tool-registry`, `mcp-client`
4. **IAM**: Delete roles
