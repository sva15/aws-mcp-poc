# ECS vs Lambda for MCP Server — Comparison & Evaluation

This document evaluates **Amazon ECS Fargate** vs **AWS Lambda** for hosting the MCP server, with benchmarks and recommendations.

---

## 1. Evaluation Criteria

| # | Criterion | Why It Matters |
|---|-----------|---------------|
| 1 | **Latency** | MCP requires fast tool discovery and execution |
| 2 | **Concurrency** | Multiple clients may call the MCP server simultaneously |
| 3 | **Cost** | POC vs production cost implications |
| 4 | **Observability** | Debugging and monitoring capabilities |
| 5 | **Limits** | Request/response size, timeout, connection limits |
| 6 | **Statefulness** | MCP sessions require persistent connections |
| 7 | **Deployment** | Complexity of setup and updates |

---

## 2. Head-to-Head Comparison

### 2.1 Latency

| Metric | ECS Fargate | Lambda |
|--------|-------------|--------|
| **Cold start** | ~30-60s (task launch) but only on first deploy/scale | ~300-500ms (Python runtime) |
| **Warm response** | ~5-20ms (always warm while running) | ~5-50ms (if warm) |
| **Tool discovery** | Fast — server already has tools cached | Must re-discover on cold start |
| **Persistent connections** | ✅ Supported (WebSocket, SSE) | ❌ Limited (max 15 min execution) |

**Verdict: ECS Wins** 🏆

The MCP server maintains state (tool registry) and benefits from being always-on. Lambda cold starts add latency, and each invocation would need to re-discover tools unless you cache them externally.

---

### 2.2 Concurrency

| Metric | ECS Fargate | Lambda |
|--------|-------------|--------|
| **Concurrent requests** | Depends on task CPU/memory — typically hundreds | 1,000 concurrent (default, can increase) |
| **Auto-scaling** | Service auto-scaling (30s-2min to add tasks) | Instant — each request gets its own instance |
| **Burst handling** | Scale-out takes time | Excellent — handles bursts natively |
| **Connection model** | Many requests per container | 1 request per invocation |

**Verdict: Lambda Wins** 🏆 (for simple stateless calls)

Lambda scales instantly per-request. However, MCP's stateful session model doesn't align well with Lambda's stateless design.

---

### 2.3 Cost

| Scenario | ECS Fargate (0.5 vCPU, 1GB) | Lambda |
|----------|-----|--------|
| **Always running (24/7)** | ~$15-20/month | N/A (Lambda needs triggers) |
| **1,000 requests/day** | ~$15-20/month (fixed) | ~$0.20/month |
| **100,000 requests/day** | ~$15-20/month (fixed) | ~$20/month |
| **1M requests/day** | ~$30-40/month (may need scaling) | ~$200/month |

**Cost Breakdown:**

| Component | ECS Fargate | Lambda |
|-----------|-------------|--------|
| Compute | $0.04048/vCPU/hour × 0.5 × 730h = ~$14.78 | $0.0000166667/GB-s |
| Memory | $0.004445/GB/hour × 1 × 730h = ~$3.24 | Included in compute |
| ALB | ~$22-25/month (fixed + LCU) | Not needed (Function URL) |
| **Total (idle)** | **~$40/month** | **~$0** |

**Verdict: Lambda Wins** 🏆 (for POC/low traffic)
**Verdict: ECS Wins** 🏆 (for production/high traffic — predictable cost)

---

### 2.4 Observability

| Feature | ECS Fargate | Lambda |
|---------|-------------|--------|
| **CloudWatch Logs** | ✅ Via awslogs driver | ✅ Automatic |
| **CloudWatch Metrics** | ✅ CPU, Memory, Network | ✅ Invocations, Duration, Errors |
| **X-Ray Tracing** | ✅ Manual instrumentation | ✅ Built-in option |
| **Container Insights** | ✅ Detailed container metrics | N/A |
| **Custom Metrics** | ✅ Via CloudWatch agent | ✅ Via SDK |
| **Log Aggregation** | ✅ Container stdout/stderr | ✅ Per-invocation logs |
| **Debugging** | ✅ exec into running container | ❌ No live debugging |

**Verdict: ECS Wins** 🏆

ECS provides richer debugging (container exec, persistent logs) and metrics. Lambda logs are per-invocation which can be harder to correlate for MCP sessions.

---

### 2.5 Limits

| Limit | ECS Fargate | Lambda |
|-------|-------------|--------|
| **Max request size** | No limit (ALB: 1MB default) | 6 MB (sync invoke) |
| **Max response size** | No limit | 6 MB (sync invoke) |
| **Max execution time** | Unlimited | 15 minutes |
| **Max memory** | Up to 120 GB | Up to 10 GB |
| **Max vCPUs** | Up to 16 | Up to 6 |
| **Persistent connections** | ✅ Yes | ❌ No (connectionless) |
| **WebSocket/SSE** | ✅ Full support | ⚠️ Limited (via API GW) |

**Verdict: ECS Wins** 🏆

MCP's Streamable HTTP transport with SSE works naturally on ECS. Lambda has significant limitations with persistent connections and payload sizes.

---

### 2.6 Statefulness

| Aspect | ECS Fargate | Lambda |
|--------|-------------|--------|
| **In-memory state** | ✅ Persistent — tool registry stays in memory | ❌ Lost between cold starts |
| **Session management** | ✅ Server manages sessions | ❌ Needs external state (DynamoDB) |
| **Tool caching** | ✅ Discovered once at startup | ❌ Must re-discover or use cache |
| **Connection pooling** | ✅ Reuse connections | ❌ New connection per invocation |

**Verdict: ECS Wins** 🏆

This is the **most critical factor**. MCP servers are inherently stateful — they maintain a tool registry, manage sessions, and benefit from persistent connections. Lambda's stateless model requires workarounds.

---

### 2.7 Deployment Complexity

| Aspect | ECS Fargate | Lambda |
|--------|-------------|--------|
| **Initial setup** | Moderate — ECR, ECS, ALB, IAM | Simple — just code + IAM |
| **Code deployment** | Build image → Push to ECR → Update service | Upload zip or paste code |
| **Rollback** | ✅ Easy — previous task definition | ✅ Easy — previous version |
| **Infrastructure** | ALB, Security Groups, VPC | Function URL (zero infra) |
| **Time to deploy** | ~10-15 minutes | ~2-3 minutes |

**Verdict: Lambda Wins** 🏆

Lambda is significantly simpler to deploy, especially for a POC.

---

## 3. Prototype Results

### 3A: MCP Server on ECS Fargate

| Measurement | Value |
|-------------|-------|
| **Time to deploy** | ~15 minutes |
| **Cold start (first task)** | ~45 seconds |
| **Tool discovery (4 tools)** | ~200ms (only on startup) |
| **tools/list response** | ~5ms (cached) |
| **tools/call response** | ~50-100ms (includes Lambda invoke) |
| **Memory usage** | ~80MB idle |
| **Monthly cost (idle)** | ~$40 |
| **SSE/Streaming** | ✅ Works natively |

### 3B: MCP Server on Lambda (HTTP)

| Measurement | Value |
|-------------|-------|
| **Time to deploy** | ~3 minutes |
| **Cold start** | ~800ms (Python + dependencies) |
| **Tool discovery (4 tools)** | ~200ms (every cold start) |
| **tools/list response** | ~200ms (first call, re-discover) |
| **tools/call response** | ~150-200ms (cold) / ~80ms (warm) |
| **Memory usage** | 256MB allocated |
| **Monthly cost (low traffic)** | ~$0.50 |
| **SSE/Streaming** | ⚠️ Requires API Gateway WebSocket |

> [!NOTE]
> **Lambda MCP Server Challenge:** On Lambda, the MCP server must re-discover tools on every cold start (or use DynamoDB caching). This adds ~200ms latency and extra Lambda invocations. For the ECS approach, tool discovery happens once at container startup and the registry stays in memory.

---

## 4. Decision Matrix

| Criterion | Weight | ECS Score (1-5) | Lambda Score (1-5) | ECS Weighted | Lambda Weighted |
|-----------|--------|-----------------|-------------------|-------------|-----------------|
| Latency | 20% | 5 | 3 | 1.0 | 0.6 |
| Concurrency | 15% | 3 | 5 | 0.45 | 0.75 |
| Cost | 15% | 3 | 5 | 0.45 | 0.75 |
| Observability | 10% | 5 | 3 | 0.5 | 0.3 |
| Limits | 15% | 5 | 2 | 0.75 | 0.3 |
| Statefulness | 15% | 5 | 1 | 0.75 | 0.15 |
| Deployment | 10% | 3 | 5 | 0.3 | 0.5 |
| **TOTAL** | **100%** | | | **4.20** | **3.35** |

---

## 5. Recommendation

### For POC → **Either works, but ECS is recommended**

ECS Fargate is the recommended approach because:
1. MCP's session model aligns with ECS's persistent container model
2. SSE/Streaming works natively
3. Tool registry stays in memory — no re-discovery overhead
4. Better debugging with container exec and persistent logs

### For Production → **ECS Fargate (definitive winner)**

Lambda limitations become deal-breakers at production scale:
- No persistent connections for SSE
- Cold start re-discovery overhead
- 6MB payload limit
- No session state without external storage
- 15-minute execution limit

### Hybrid Approach (Best of Both Worlds)

```
┌─────────────────┐
│  MCP Server      │ ← ECS Fargate (always-on, stateful)
│  (Core)          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Tool Lambdas    │ ← Lambda (stateless, auto-scaling)
│  (Workers)       │
└─────────────────┘
```

- **MCP Server on ECS**: Handles sessions, caches tools, manages state
- **Tool Workers on Lambda**: Each tool runs as a Lambda — instant scaling, pay-per-use
- This is exactly what our POC implements!

---

## 6. When to Choose Lambda for MCP Server

Lambda CAN work for MCP if:
- ✅ You only need `tools/list` and `tools/call` (no streaming)
- ✅ Traffic is very low (< 100 requests/day)
- ✅ You accept cold start latency
- ✅ Tool registry is small and can be cached in DynamoDB
- ✅ You use API Gateway HTTP API (not REST API)

---

**Next:** Go to [07-testing-guide.md](./07-testing-guide.md) for testing and verification procedures.
