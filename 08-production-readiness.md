# Production Readiness Guide

Steps to evolve this POC into a production-grade MCP server deployment.

---

## POC vs Production Gap Analysis

| Area | POC (Current) | Production (Target) |
|------|--------------|---------------------|
| **Networking** | Public ALB | Internal ALB + VPC endpoints |
| **Auth** | None | API keys, IAM, or mTLS |
| **Scaling** | 1 ECS task | Auto-scaling (2-10 tasks) |
| **Availability** | Single AZ possible | Multi-AZ guaranteed |
| **Monitoring** | Basic CloudWatch | Dashboards, alarms, X-Ray |
| **CI/CD** | Manual Console deploy | CodePipeline / GitHub Actions |
| **Security** | Broad IAM permissions | Least-privilege, VPC endpoints |
| **Error handling** | Basic logging | Retry logic, DLQ, circuit breakers |
| **Secrets** | Env vars | AWS Secrets Manager |
| **Tool discovery** | At startup only | Periodic refresh + cache |

---

## Phase 1: Security Hardening

### 1.1: Internal ALB + VPC

```
Before (POC):
  Client Lambda → Internet → Public ALB → ECS

After (Production):
  Client Lambda (VPC) → Internal ALB → ECS (same VPC)
```

**Steps:**
1. Change ALB scheme from "internet-facing" to "internal"
2. Place Client Lambda in the same VPC
3. Add VPC endpoint for Lambda service (for tool invocations)
4. Remove all public internet access

### 1.2: Authentication

Add API key authentication to the MCP server:

```python
# In server.py — add middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        
        api_key = request.headers.get("X-API-Key", "")
        expected_key = os.environ.get("MCP_API_KEY", "")
        
        if not expected_key or api_key != expected_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
        return await call_next(request)
```

Store the API key in **AWS Secrets Manager** and inject via ECS task definition.

### 1.3: Least-Privilege IAM

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": [
                "arn:aws:lambda:us-east-1:123456789:function:mcp-tool-math",
                "arn:aws:lambda:us-east-1:123456789:function:mcp-tool-string"
            ]
        }
    ]
}
```

Use **specific ARNs** instead of wildcards.

---

## Phase 2: High Availability & Scaling

### 2.1: Auto-Scaling

1. Go to **ECS Console** → Service → **Update** → **Service Auto Scaling**
2. Configure:
   - **Minimum tasks**: 2
   - **Maximum tasks**: 10
   - **Target tracking**: CPU at 60%
   - **Scale-in cooldown**: 300 seconds
   - **Scale-out cooldown**: 60 seconds

### 2.2: Multi-AZ

1. Ensure ECS service subnets span **at least 2 Availability Zones**
2. ALB is already multi-AZ by default
3. Minimum 2 tasks ensures one per AZ

### 2.3: Task Definition Updates

```
CPU: 1 vCPU (1024)
Memory: 2 GB (2048)
```

Increase resources for production workload.

---

## Phase 3: Monitoring & Alerting

### 3.1: CloudWatch Dashboard

Create a dashboard with these widgets:

| Widget | Metric | Source |
|--------|--------|--------|
| ECS CPU | `CPUUtilization` | ECS Service |
| ECS Memory | `MemoryUtilization` | ECS Service |
| ALB Requests | `RequestCount` | ALB |
| ALB Latency | `TargetResponseTime` | ALB |
| ALB 5xx Errors | `HTTPCode_Target_5XX_Count` | ALB |
| Lambda Errors | `Errors` | Each Lambda |
| Lambda Duration | `Duration` | Each Lambda |

### 3.2: CloudWatch Alarms

| Alarm | Condition | Action |
|-------|-----------|--------|
| High CPU | CPU > 80% for 5 min | SNS notification |
| High Latency | p99 > 2s for 5 min | SNS notification |
| 5xx Errors | > 10 in 5 min | SNS notification |
| Unhealthy Targets | Count > 0 for 3 min | SNS notification |
| Task Count 0 | Running tasks = 0 | SNS + PagerDuty |

### 3.3: X-Ray Tracing

Add to MCP server:
```python
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.ext.fastapi.middleware import XRayMiddleware

XRayMiddleware(app, xray_recorder)
```

Enable X-Ray on tool Lambdas via console: **Configuration** → **Monitoring** → **Active tracing** → **Enable**.

---

## Phase 4: CI/CD Pipeline

### GitHub Actions Workflow

```yaml
name: Deploy MCP Server
on:
  push:
    branches: [main]
    paths: ['mcp-server/**']

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::ACCOUNT:role/github-actions-role
          aws-region: us-east-1

      - name: Login to ECR
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build & push image
        run: |
          cd mcp-server
          docker build -t mcp-server .
          docker tag mcp-server:latest $ECR_URI:${{ github.sha }}
          docker tag mcp-server:latest $ECR_URI:latest
          docker push $ECR_URI:${{ github.sha }}
          docker push $ECR_URI:latest

      - name: Update ECS service
        run: |
          aws ecs update-service \
            --cluster mcp-cluster \
            --service mcp-server-service \
            --force-new-deployment
```

---

## Phase 5: Error Handling & Resilience

### 5.1: Tool Discovery Retry

```python
import time

def discover_tools_with_retry(max_retries=3, delay=5):
    for attempt in range(max_retries):
        try:
            discover_tools()
            if tool_registry:
                return
            logger.warning(f"No tools found, attempt {attempt + 1}/{max_retries}")
        except Exception as e:
            logger.error(f"Discovery failed, attempt {attempt + 1}: {e}")
        time.sleep(delay * (attempt + 1))
    
    logger.error("Tool discovery failed after all retries")
```

### 5.2: Tool Call Retry

```python
def invoke_tool_with_retry(lambda_name, tool_name, arguments, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            return invoke_tool_lambda(lambda_name, tool_name, arguments)
        except Exception as e:
            if attempt == max_retries:
                raise
            logger.warning(f"Retry {attempt + 1} for {tool_name}: {e}")
            time.sleep(1)
```

### 5.3: Periodic Tool Refresh

```python
import threading

def periodic_refresh(interval=300):  # 5 minutes
    while True:
        time.sleep(interval)
        logger.info("Periodic tool refresh...")
        discover_tools()
        register_tools()

refresh_thread = threading.Thread(target=periodic_refresh, daemon=True)
refresh_thread.start()
```

---

## Phase 6: Infrastructure as Code (Optional)

### Terraform Example

```hcl
# ecs.tf
resource "aws_ecs_service" "mcp_server" {
  name            = "mcp-server-service"
  cluster         = aws_ecs_cluster.mcp.id
  task_definition = aws_ecs_task_definition.mcp_server.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.mcp_ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mcp.arn
    container_name   = "mcp-server"
    container_port   = 8000
  }
}
```

---

## Production Checklist

| # | Item | Status |
|---|------|--------|
| 1 | Internal ALB (no public access) | ☐ |
| 2 | Authentication (API keys or IAM) | ☐ |
| 3 | Least-privilege IAM roles | ☐ |
| 4 | Multi-AZ deployment (min 2 tasks) | ☐ |
| 5 | Auto-scaling configured | ☐ |
| 6 | CloudWatch dashboard | ☐ |
| 7 | CloudWatch alarms (CPU, latency, errors) | ☐ |
| 8 | X-Ray tracing enabled | ☐ |
| 9 | CI/CD pipeline (GitHub Actions or CodePipeline) | ☐ |
| 10 | Error handling & retries | ☐ |
| 11 | Periodic tool refresh | ☐ |
| 12 | Secrets in Secrets Manager | ☐ |
| 13 | VPC endpoints for Lambda/ECR | ☐ |
| 14 | Access logging on ALB | ☐ |
| 15 | Container vulnerability scanning (ECR) | ☐ |
| 16 | Resource tagging (cost allocation) | ☐ |
| 17 | Backup/disaster recovery plan | ☐ |
| 18 | Load testing completed | ☐ |
| 19 | Runbook/playbook for operations | ☐ |
| 20 | Infrastructure as Code (Terraform/CDK) | ☐ |

---

## Summary: POC → Production Timeline

| Week | Focus | Deliverables |
|------|-------|-------------|
| 1 | POC Complete | All tests pass, comparison done |
| 2 | Security | Internal ALB, auth, IAM hardening |
| 3 | HA & Scaling | Multi-AZ, auto-scaling, load testing |
| 4 | Monitoring | Dashboard, alarms, X-Ray |
| 5 | CI/CD | Pipeline, IaC, staging environment |
| 6 | Production | Deploy, validate, handover |
