# ECS Deployment Guide — Step by Step via AWS Console

---

## Deployment Order

```
Step 1: Enable Bedrock Model Access
Step 2: Create IAM Roles (x3)
Step 3: Deploy Tool Lambda Functions (x4)
Step 4: Test Tool Lambdas
Step 5: Push MCP Server Image to ECR
Step 6: Create ECS Cluster, Task Definition, Service with ALB
Step 7: Verify MCP Server Health
Step 8: Deploy Client Lambda
Step 9: Test End-to-End
```

**Estimated time: 45-60 minutes**

---

## Step 1: Enable Bedrock Model Access

1. Go to **Amazon Bedrock Console** → [console.aws.amazon.com/bedrock](https://console.aws.amazon.com/bedrock)
2. Select your region (e.g., `us-east-1`)
3. **Model access** → **Manage model access**
4. Check **Anthropic → Claude 3 Sonnet** (or **Amazon → Nova Lite** for cheaper)
5. **Request model access** → wait for **Access granted**

---

## Step 2: Create IAM Roles

### 2A: Tool Lambda Role

1. **IAM** → **Roles** → **Create Role** → Lambda → `AWSLambdaBasicExecutionRole`
2. **Name**: `mcp-tool-lambda-role`

### 2B: MCP Server ECS Task Role

1. **IAM** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Elastic Container Service** → **Elastic Container Service Task**
3. **Attach policy**: `AWSLambdaBasicExecutionRole` (for CloudWatch logs)
4. **Create inline policy** → JSON:

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

5. **Policy name**: `mcp-server-tool-access`
6. **Role name**: `mcp-server-ecs-task-role`

### 2C: ECS Task Execution Role

> This role lets ECS pull images from ECR and write logs.

1. **IAM** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Elastic Container Service** → **Elastic Container Service Task**
3. **Attach policy**: `AmazonECSTaskExecutionRolePolicy`
4. **Role name**: `ecsTaskExecutionRole` (may already exist)

### 2D: Client Lambda Role

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

> **Note**: The client Lambda calls the MCP Server via HTTP (ALB URL), NOT via Lambda invoke. So no `lambda:InvokeFunction` permission needed.

3. **Policy name**: `mcp-client-bedrock-access`
4. **Role name**: `mcp-client-lambda-role`

### Also: Create a VPC Security Group for ALB + ECS

1. **VPC** → **Security Groups** → **Create**
2. **Name**: `mcp-server-sg`
3. **Inbound rules**:
   - Port 80 (HTTP) from `0.0.0.0/0` (ALB)
   - Port 8000 from the security group itself (ECS ↔ ALB)
4. **Outbound**: All traffic

---

## Step 3: Deploy Tool Lambda Functions

Create 4 Lambda functions, all using:
- **Runtime**: Python 3.12
- **Role**: `mcp-tool-lambda-role`
- **Timeout**: 30 seconds

| Lambda Name | Code Source |
|-------------|-----------|
| `mcp-tool-math` | `tool-lambdas/math_tools/lambda_function.py` |
| `mcp-tool-string` | `tool-lambdas/string_tools/lambda_function.py` |
| `mcp-tool-time` | `tool-lambdas/datetime_tools/lambda_function.py` |
| `mcp-tool-utility` | `tool-lambdas/utility_tools/lambda_function.py` |

For each: Create Function → Paste code → **Deploy**

---

## Step 4: Test Tool Lambdas

Test each with these events in the Lambda console **Test** tab:

**Describe test (all):**
```json
{"action": "__describe__"}
```

**Call test examples:**
```json
{"action": "__call__", "tool": "add", "arguments": {"a": 5, "b": 3}}
{"action": "__call__", "tool": "uppercase", "arguments": {"text": "hello"}}
{"action": "__call__", "tool": "current_time", "arguments": {}}
{"action": "__call__", "tool": "is_palindrome", "arguments": {"text": "racecar"}}
```

✅ All must pass before proceeding.

---

## Step 5: Push MCP Server Image to ECR

### 5A: Create ECR Repository

1. **ECR Console** → **Create repository**
2. **Name**: `mcp-server`
3. **Visibility**: Private
4. Click **Create**

### 5B: Build and Push Docker Image

On your local machine (requires Docker and AWS CLI):

```bash
# Set your AWS account ID and region
export AWS_ACCOUNT_ID=123456789012
export AWS_REGION=us-east-1

# Authenticate Docker with ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build the image (run from ecs-based-poc/mcp-server/)
cd mcp-server
docker build -t mcp-server .

# Tag for ECR
docker tag mcp-server:latest \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/mcp-server:latest

# Push to ECR
docker push \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/mcp-server:latest
```

---

## Step 6: Create ECS Cluster + Service + ALB

### 6A: Create ECS Cluster

1. **ECS Console** → **Clusters** → **Create cluster**
2. **Cluster name**: `mcp-cluster`
3. **Infrastructure**: AWS Fargate (serverless)
4. Click **Create**

### 6B: Create Task Definition

1. **ECS Console** → **Task definitions** → **Create new task definition** → **JSON**

```json
{
    "family": "mcp-server",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "512",
    "memory": "1024",
    "taskRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/mcp-server-ecs-task-role",
    "executionRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/ecsTaskExecutionRole",
    "containerDefinitions": [
        {
            "name": "mcp-server",
            "image": "YOUR_ACCOUNT.dkr.ecr.YOUR_REGION.amazonaws.com/mcp-server:latest",
            "portMappings": [
                {"containerPort": 8000, "protocol": "tcp"}
            ],
            "environment": [
                {"name": "AWS_REGION", "value": "us-east-1"},
                {"name": "TOOL_PREFIX", "value": "mcp-tool-"},
                {"name": "CACHE_TTL", "value": "300"},
                {"name": "LOG_LEVEL", "value": "INFO"}
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/ecs/mcp-server",
                    "awslogs-region": "us-east-1",
                    "awslogs-stream-prefix": "mcp",
                    "awslogs-create-group": "true"
                }
            },
            "healthCheck": {
                "command": ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
                "interval": 30,
                "timeout": 5,
                "retries": 3,
                "startPeriod": 60
            }
        }
    ]
}
```

> Replace `YOUR_ACCOUNT` and `YOUR_REGION` with your values.

### 6C: Create Application Load Balancer

1. **EC2 Console** → **Load Balancers** → **Create** → **Application Load Balancer**
2. **Name**: `mcp-server-alb`
3. **Scheme**: Internal (if Client Lambda is in same VPC) or Internet-facing (for testing)
4. **Listeners**: HTTP Port 80
5. **VPC**: Select your VPC and at least 2 subnets
6. **Security group**: `mcp-server-sg`

**Create Target Group:**
1. **Target type**: IP addresses
2. **Name**: `mcp-server-tg`
3. **Port**: 8000
4. **Protocol**: HTTP
5. **Health check path**: `/health`
6. **Health check interval**: 30s
7. Register targets later (ECS will register containers)

**Set ALB listener** to forward to `mcp-server-tg`.

### 6D: Create ECS Service

1. **ECS Console** → **mcp-cluster** → **Create Service**
2. **Launch type**: FARGATE
3. **Task definition**: `mcp-server` (latest)
4. **Service name**: `mcp-server-service`
5. **Desired tasks**: 1 (increase for HA)
6. **Networking**: Select your VPC, subnets, `mcp-server-sg`
7. **Load balancing**: 
   - Application Load Balancer → `mcp-server-alb`
   - Container: `mcp-server:8000`
   - Target group: `mcp-server-tg`
8. Click **Create Service**

Wait for the service to reach **RUNNING** status.

---

## Step 7: Verify MCP Server Health

### Get ALB DNS

Go to **EC2** → **Load Balancers** → `mcp-server-alb` → copy DNS name.

### Health Check

```
curl http://<ALB-DNS>/health
```

Expected:
```json
{
    "status": "healthy",
    "server": "aws-mcp-server",
    "version": "1.0.0",
    "tools_discovered": 14,
    "tool_names": ["add", "multiply", "subtract", "divide", "uppercase", ...]
}
```

### Test tools/list via MCP Protocol

```bash
curl -X POST http://<ALB-DNS>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

✅ Should return all 14 tools.

---

## Step 8: Deploy Client Lambda

1. **Lambda Console** → **Create Function**
2. **Name**: `mcp-client`
3. **Runtime**: Python 3.12
4. **Role**: `mcp-client-lambda-role`
5. Paste code from: `client-lambda/lambda_function.py`
6. **Deploy**

### Configure:

- **Timeout**: 120 seconds
- **Memory**: 256 MB
- **VPC**: Same VPC as the ECS service (if ALB is internal)

**Environment Variables:**

| Key | Value |
|-----|-------|
| `AWS_REGION` | `us-east-1` |
| `MCP_SERVER_URL` | `http://<ALB-DNS>/mcp` |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-sonnet-20240229-v1:0` |

> **Important**: Replace `<ALB-DNS>` with your actual ALB DNS name!

---

## Step 9: Test End-to-End

### Test 1: List Tools
```json
{"action": "list_tools"}
```
✅ Should return 14 tools

### Test 2: Math Question
```json
{"question": "What is 15 multiplied by 27?"}
```
✅ Should use `multiply` tool, answer "405"

### Test 3: String Question
```json
{"question": "Reverse the word Lambda"}
```
✅ Should use `reverse` tool

### Test 4: Time Question
```json
{"question": "What is today's date?"}
```
✅ Should use `current_time` tool

### Test 5: Utility Question
```json
{"question": "Convert 100 degrees Celsius to Fahrenheit"}
```
✅ Should use `convert_temperature` tool, answer "212°F"

### Test 6: No Tool Needed
```json
{"question": "What is the capital of France?"}
```
✅ Should answer directly without using tools

---

## Resource Cleanup

1. **ECS**: Delete service → delete cluster
2. **ECR**: Delete mcp-server repository
3. **ALB**: Delete load balancer → delete target group
4. **Lambda**: Delete all `mcp-tool-*` and `mcp-client`
5. **IAM**: Delete roles and inline policies
6. **CloudWatch**: Delete log groups `/ecs/mcp-server` and `/aws/lambda/mcp-*`

---

**Next →** [03-testing-guide.md](./03-testing-guide.md) — Complete test suite
