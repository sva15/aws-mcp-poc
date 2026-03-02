# AWS Console Deployment Guide — Step by Step

This guide walks you through deploying the entire MCP POC using the **AWS Console only** — no CLI or IaC required.

---

## Deployment Order

```
Step 1: Create IAM Roles
Step 2: Deploy Tool Lambda Functions
Step 3: Test Tool Lambdas
Step 4: Build & Push Docker Image to ECR
Step 5: Create ECS Cluster
Step 6: Create Task Definition
Step 7: Create ALB (Application Load Balancer)
Step 8: Create ECS Service
Step 9: Deploy Client Lambda
Step 10: Test End-to-End
```

---

## Prerequisites

- AWS Account with admin access
- Docker installed locally (to build the MCP server image)
- AWS CLI configured locally (only for `docker push` to ECR)
- The source code files from docs 02-04

---

## Step 1: Create IAM Roles

### 1A: ECS Task Execution Role

This role allows ECS to pull images from ECR and write logs.

1. Go to **IAM Console** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Elastic Container Service** → **Elastic Container Service Task**
3. **Permissions**: Attach `AmazonECSTaskExecutionRolePolicy`
4. **Role name**: `mcp-ecs-task-execution-role`
5. Click **Create Role**

### 1B: ECS Task Role (for the MCP Server)

This role allows the MCP server container to invoke Lambda functions.

1. Go to **IAM Console** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Elastic Container Service** → **Elastic Container Service Task**
3. **Permissions**: Click **Create Policy** (opens new tab):

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

4. **Policy name**: `mcp-invoke-tool-lambdas`
5. Go back to role creation, attach this policy
6. **Role name**: `mcp-ecs-task-role`
7. Click **Create Role**

### 1C: Lambda Execution Roles

#### Tool Lambda Role:
1. Go to **IAM Console** → **Roles** → **Create Role**
2. **Trusted entity**: AWS Service → **Lambda**
3. **Permissions**: Attach `AWSLambdaBasicExecutionRole`
4. **Role name**: `mcp-tool-lambda-role`
5. Click **Create Role**

#### Client Lambda Role:
1. Same as above
2. **Permissions**: Attach `AWSLambdaBasicExecutionRole`
3. **Role name**: `mcp-client-lambda-role`
4. Click **Create Role**

> **Summary of Roles Created:**
>
> | Role Name | Purpose | Key Permission |
> |-----------|---------|---------------|
> | `mcp-ecs-task-execution-role` | ECS pulls images, writes logs | `AmazonECSTaskExecutionRolePolicy` |
> | `mcp-ecs-task-role` | MCP server invokes tool Lambdas | `lambda:InvokeFunction` on `mcp-tool-*` |
> | `mcp-tool-lambda-role` | Tool Lambdas write logs | `AWSLambdaBasicExecutionRole` |
> | `mcp-client-lambda-role` | Client Lambda writes logs | `AWSLambdaBasicExecutionRole` |

---

## Step 2: Deploy Tool Lambda Functions

### 2A: Math Tools Lambda

1. Go to **Lambda Console** → **Create Function**
2. **Function name**: `mcp-tool-math`
3. **Runtime**: Python 3.12
4. **Architecture**: x86_64
5. **Execution role**: Use existing role → `mcp-tool-lambda-role`
6. Click **Create Function**
7. In the **Code** tab, replace the default code with the contents of `tool-lambdas/math_tools/lambda_function.py`
8. Click **Deploy**

### 2B: String Tools Lambda

1. Go to **Lambda Console** → **Create Function**
2. **Function name**: `mcp-tool-string`
3. **Runtime**: Python 3.12
4. **Architecture**: x86_64
5. **Execution role**: Use existing role → `mcp-tool-lambda-role`
6. Click **Create Function**
7. In the **Code** tab, replace the default code with the contents of `tool-lambdas/string_tools/lambda_function.py`
8. Click **Deploy**

---

## Step 3: Test Tool Lambdas

### Test Math Lambda:

1. Go to `mcp-tool-math` → **Test** tab
2. Create test event named `TestDescribe`:
```json
{
  "action": "__describe__"
}
```
3. Click **Test** — you should see the tool definitions
4. Create test event named `TestAdd`:
```json
{
  "action": "__call__",
  "tool": "add",
  "arguments": {"a": 5, "b": 3}
}
```
5. Click **Test** — should return `{"result": 8}`

### Test String Lambda:

1. Go to `mcp-tool-string` → **Test** tab
2. Create test event named `TestDescribe`:
```json
{
  "action": "__describe__"
}
```
3. Click **Test** — you should see the tool definitions
4. Create test event named `TestUppercase`:
```json
{
  "action": "__call__",
  "tool": "uppercase",
  "arguments": {"text": "hello world"}
}
```
5. Click **Test** — should return `{"result": "HELLO WORLD"}`

> [!IMPORTANT]
> **Do NOT proceed to Step 4 until both tool Lambdas pass all tests!**

---

## Step 4: Build & Push Docker Image to ECR

### 4A: Create ECR Repository

1. Go to **ECR Console** → **Create Repository**
2. **Repository name**: `mcp-server`
3. **Image tag mutability**: Mutable
4. Click **Create Repository**

### 4B: Build and Push Docker Image

Open a terminal on your local machine. Navigate to the `mcp-server/` directory.

```bash
# 1. Login to ECR (replace ACCOUNT_ID and REGION)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# 2. Build the Docker image
docker build -t mcp-server .

# 3. Tag the image
docker tag mcp-server:latest ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/mcp-server:latest

# 4. Push the image
docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/mcp-server:latest
```

> **Replace `ACCOUNT_ID` with your actual AWS account ID and `us-east-1` with your region.**

### 4C: Verify

Go to **ECR Console** → `mcp-server` repository → You should see the `latest` image tag.

---

## Step 5: Create ECS Cluster

1. Go to **ECS Console** → **Clusters** → **Create Cluster**
2. **Cluster name**: `mcp-cluster`
3. **Infrastructure**: AWS Fargate (serverless)
4. Click **Create**

---

## Step 6: Create Task Definition

1. Go to **ECS Console** → **Task Definitions** → **Create new task definition**
2. **Task definition family**: `mcp-server-task`
3. **Launch type**: AWS Fargate
4. **Operating system/Architecture**: Linux/X86_64
5. **Task size**:
   - CPU: `0.5 vCPU` (512)
   - Memory: `1 GB` (1024)
6. **Task role**: `mcp-ecs-task-role`
7. **Task execution role**: `mcp-ecs-task-execution-role`

### Container Definition:

8. Click **Add Container**
9. **Container name**: `mcp-server`
10. **Image URI**: `ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/mcp-server:latest`
11. **Port mappings**: Container port `8000`, Protocol `TCP`
12. **Environment variables**:

| Key | Value |
|-----|-------|
| `TOOL_LAMBDA_ARNS` | `mcp-tool-math,mcp-tool-string` |
| `AWS_REGION` | `us-east-1` |

13. **Log configuration**: 
    - Log driver: `awslogs`
    - awslogs-group: `/ecs/mcp-server`
    - awslogs-region: `us-east-1`
    - awslogs-stream-prefix: `mcp`

14. Click **Create**

> [!NOTE]
> The `TOOL_LAMBDA_ARNS` environment variable is a comma-separated list of Lambda function names. The MCP server will query each one on startup to discover tools.

---

## Step 7: Create Application Load Balancer (ALB)

### 7A: Create Target Group

1. Go to **EC2 Console** → **Target Groups** → **Create Target Group**
2. **Target type**: IP addresses
3. **Target group name**: `mcp-server-tg`
4. **Protocol**: HTTP
5. **Port**: 8000
6. **VPC**: Select your default VPC
7. **Health check path**: `/health`
8. **Health check protocol**: HTTP
9. Click **Create Target Group**

### 7B: Create ALB

1. Go to **EC2 Console** → **Load Balancers** → **Create Load Balancer**
2. Select **Application Load Balancer**
3. **Load balancer name**: `mcp-alb`
4. **Scheme**: Internet-facing (for POC simplicity)
5. **IP address type**: IPv4
6. **VPC**: Select your default VPC
7. **Availability Zones**: Select at least 2 subnets
8. **Security Group**: Create new:
   - **Name**: `mcp-alb-sg`
   - **Inbound rule**: HTTP (port 80) from `0.0.0.0/0`
9. **Listeners**:
   - Protocol: HTTP, Port: 80
   - Default action: Forward to `mcp-server-tg`
10. Click **Create Load Balancer**

### 7C: Note the ALB DNS

After creation, go to the ALB details and copy the **DNS name**:
```
Example: mcp-alb-123456789.us-east-1.elb.amazonaws.com
```

You'll need this for the Client Lambda's `MCP_SERVER_URL` environment variable.

---

## Step 8: Create ECS Service

1. Go to **ECS Console** → `mcp-cluster` → **Services** → **Create**
2. **Launch type**: Fargate
3. **Task definition**: `mcp-server-task` (latest revision)
4. **Service name**: `mcp-server-service`
5. **Desired tasks**: 1
6. **Networking**:
   - VPC: Same as ALB
   - Subnets: Same subnets as ALB
   - Security group: Create new:
     - **Name**: `mcp-ecs-sg`
     - **Inbound**: Custom TCP, Port 8000, Source: `mcp-alb-sg` (the ALB security group)
   - Public IP: TURNED ON (so ECS can pull image from ECR and invoke Lambda)
7. **Load balancing**:
   - Load balancer type: Application Load Balancer
   - Load balancer: `mcp-alb`
   - Container: `mcp-server:8000`
   - Target group: `mcp-server-tg`
8. Click **Create Service**

### Wait for Service to Stabilize

1. Go to `mcp-cluster` → `mcp-server-service` → **Tasks** tab
2. Wait for the task status to show **RUNNING**
3. Check **Logs** tab — you should see:
```
INFO:mcp-server:Discovering tools from 2 Lambda functions...
INFO:mcp-server:  Querying: mcp-tool-math
INFO:mcp-server:    Registered tool: add
INFO:mcp-server:    Registered tool: multiply
INFO:mcp-server:  Querying: mcp-tool-string
INFO:mcp-server:    Registered tool: uppercase
INFO:mcp-server:    Registered tool: reverse
INFO:mcp-server:Total tools discovered: 4
INFO:mcp-server:Starting MCP Server on port 8000...
```

### Verify ALB Health

1. Go to **EC2 Console** → **Target Groups** → `mcp-server-tg`
2. Check that the registered target is **healthy**
3. You can also test in browser: `http://YOUR-ALB-DNS/health`

---

## Step 9: Deploy Client Lambda

1. Go to **Lambda Console** → **Create Function**
2. **Function name**: `mcp-client`
3. **Runtime**: Python 3.12
4. **Architecture**: x86_64
5. **Execution role**: Use existing role → `mcp-client-lambda-role`
6. Click **Create Function**
7. In the **Code** tab, replace the default code with the contents of `client-lambda/lambda_function.py`
8. Click **Deploy**

### Configure Environment Variable:

9. Go to **Configuration** → **Environment variables** → **Edit**
10. Add:

| Key | Value |
|-----|-------|
| `MCP_SERVER_URL` | `http://YOUR-ALB-DNS` (e.g., `http://mcp-alb-123456789.us-east-1.elb.amazonaws.com`) |

11. Click **Save**

### Configure Timeout:

12. Go to **Configuration** → **General configuration** → **Edit**
13. Set **Timeout** to `60 seconds` (the default 3 seconds is too short)
14. Click **Save**

---

## Step 10: Test End-to-End

### Test 1: List Tools

1. Go to `mcp-client` → **Test** tab
2. Create test event:
```json
{
  "action": "list_tools"
}
```
3. Click **Test**
4. **Expected**: You should see 4 tools listed (add, multiply, uppercase, reverse)

### Test 2: Call a Tool

1. Create test event:
```json
{
  "action": "call_tool",
  "tool_name": "add",
  "arguments": {"a": 100, "b": 200}
}
```
2. Click **Test**
3. **Expected**: Result should contain `{"result": 300}`

### Test 3: Full Test

1. Create test event:
```json
{
  "action": "full_test"
}
```
2. Click **Test**
3. **Expected**: All 4 tools should return correct results

---

## Troubleshooting

### Problem: Client Lambda times out

**Cause:** Lambda can't reach the ALB.

**Fix:** 
- Ensure ALB is internet-facing (for POC)
- Increase Lambda timeout to 60 seconds
- Check ALB security group allows inbound HTTP on port 80

### Problem: ECS task fails to start

**Cause:** Image pull failure or container crash.

**Fix:**
- Check CloudWatch logs at `/ecs/mcp-server`
- Verify ECR image exists and URI is correct
- Verify task execution role has ECR pull permissions

### Problem: MCP server can't discover tools

**Cause:** ECS task role doesn't have Lambda invoke permissions.

**Fix:**
- Check `mcp-ecs-task-role` has the `mcp-invoke-tool-lambdas` policy
- Verify tool Lambda names match the `TOOL_LAMBDA_ARNS` env var exactly

### Problem: ALB health check fails

**Cause:** Container not responding on /health endpoint.

**Fix:**
- Check ECS task logs for startup errors
- Ensure container port is 8000 and target group port matches
- Verify security group allows traffic from ALB to ECS on port 8000

---

## Resource Cleanup (When Done)

To avoid charges, delete in this order:

1. **ECS**: Delete Service → Delete Cluster
2. **EC2**: Delete ALB → Delete Target Group → Delete Security Groups
3. **Lambda**: Delete all 3 Lambda functions
4. **ECR**: Delete repository (and images)
5. **IAM**: Delete roles and policies
6. **CloudWatch**: Delete log groups

---

**Next:** Go to [06-ecs-vs-lambda-comparison.md](./06-ecs-vs-lambda-comparison.md) for the ECS vs Lambda hosting evaluation.
