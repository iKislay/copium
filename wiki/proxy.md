# Proxy Server Documentation

The Copium proxy server is a production-ready HTTP server that applies context optimization to all requests passing through it.

> **New:** The proxy now supports the [TypeScript SDK](typescript-sdk.md) via the `POST /v1/compress` endpoint, enabling compression-as-a-service for any HTTP client without calling an LLM.

## Starting the Proxy

```bash
# Basic usage
copium proxy

# Custom port
copium proxy --port 8080

# With all options
copium proxy \
  --host 0.0.0.0 \
  --port 8787 \
  --log-file /var/log/copium.jsonl \
  --budget 100.0
```

### Common agent CLI entrypoints

```bash
# Claude Code
ANTHROPIC_BASE_URL=http://localhost:8787 claude

# GitHub Copilot CLI
copium wrap copilot -- --model claude-sonnet-4-20250514

# OpenAI-compatible clients
OPENAI_BASE_URL=http://localhost:8787/v1 your-app
```

`copium wrap copilot` uses Copilot CLI's BYOK provider settings under the hood. In `provider-type=auto`, it chooses Copium's Anthropic route for the default proxy backend and the OpenAI-compatible `/v1` route for translated backends such as `anyllm` and LiteLLM.

Anonymous aggregate telemetry is enabled by default. Opt out with `COPIUM_TELEMETRY=off` or `copium proxy --no-telemetry`. Downstream apps can set `COPIUM_SDK=copium-app` to override the anonymous telemetry `sdk` label; the default remains `proxy`.

Operational OTEL metrics are configured separately and are **off by default**. Install `copium-ai[proxy,otel]` and set:

```bash
COPIUM_OTEL_METRICS_ENABLED=1
COPIUM_OTEL_METRICS_EXPORTER=otlp_http
COPIUM_OTEL_METRICS_ENDPOINT=http://127.0.0.1:4318/v1/metrics
COPIUM_OTEL_SERVICE_NAME=copium-proxy
```

Use `COPIUM_OTEL_METRICS_EXPORTER=console` for local smoke testing. `COPIUM_TELEMETRY` controls the anonymous data-flywheel beacon only; it does not disable or enable OTEL export.

Langfuse can be enabled alongside this OTEL path for **trace ingestion**. Langfuse does **not** ingest OTEL metrics, so Copium keeps metrics and Langfuse traces as complementary signals:

```bash
COPIUM_LANGFUSE_ENABLED=1
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

When configured, Copium emits OTLP traces for the shared compression pipeline to Langfuse while continuing to expose metrics through `/metrics` and OTEL metric exporters.

## Command Line Options

### Core Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Host to bind to |
| `--port` | `8787` | Port to bind to |
| `--mode` | `token` | Run mode: `token` (maximize compression) or `cache` (freeze prior turns) |
| `--no-optimize` | `false` | Disable optimization (passthrough mode) |
| `--no-cache` | `false` | Disable semantic caching |
| `--no-rate-limit` | `false` | Disable rate limiting |
| `--log-file` | None | Path to JSONL log file |
| `--budget` | None | Daily budget limit in USD |
| `--code-aware` | true | Enable AST-based code compression (env: COPIUM_CODE_AWARE_ENABLED) |
| `--no-code-aware` | false | Disable code-aware compression |
| `--anthropic-api-url` | `https://api.anthropic.com` | Custom Anthropic API URL endpoint |
| `--openai-api-url` | `https://api.openai.com` | Custom OpenAI API URL endpoint |

### Run Modes

Copium proxy has two explicit run modes:

- `token` mode: prioritize token reduction. Prior history may be rewritten when that improves compression.
- `cache` mode: prioritize provider prefix cache stability. Prior turns are frozen; only the newest turn is mutable.

Set via CLI or env:

```bash
copium proxy --mode token
COPIUM_MODE=cache copium proxy
```

When to pick each:

- `token`: best for maximizing immediate compression savings.
- `cache`: best for long conversations where preserving prior-turn bytes improves prefix-cache reuse.

Legacy values (`token_copium`, `cost_savings`) are still accepted as aliases.

### Context Management Options

| Option | Default | Description |
|--------|---------|-------------|
| `--no-intelligent-context` | `false` | Disable IntelligentContextManager (fall back to RollingWindow) |
| `--no-intelligent-scoring` | `false` | Disable multi-factor importance scoring (use position-based) |
| `--no-compress-first` | `false` | Disable trying deeper compression before dropping messages |

By default, the proxy uses **IntelligentContextManager** which scores messages by multiple factors (recency, semantic similarity, TOIN-learned patterns, error indicators, forward references) and drops lowest-scored messages first. This is smarter than simple age-based truncation.

**CCR Integration:** When messages are dropped, they're stored in CCR so the LLM can retrieve them if needed. The inserted marker includes the CCR reference. Drops are also recorded to TOIN, so the system learns which message patterns are important across all users.

```bash
# Use legacy RollingWindow (drops oldest first)
copium proxy --no-intelligent-context

# Disable semantic scoring (faster, but less intelligent)
copium proxy --no-intelligent-scoring
```

### ML Compression — RETIRED `--llmlingua` flag

The `--llmlingua` / `--llmlingua-device` / `--llmlingua-rate` flags and
the `copium-ai[llmlingua]` extra were retired and replaced by Kompress
(ModernBERT). For the current opt-in path, install `copium-ai[ml]`
and see [transforms.md](transforms.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## API Endpoints

### Liveness

```bash
curl http://localhost:8787/livez
```

Response:
```json
{
  "service": "copium-proxy",
  "status": "healthy",
  "alive": true,
  "version": "0.5.21",
  "timestamp": "2026-04-10T16:36:25Z",
  "uptime_seconds": 12.483
}
```

### Readiness

```bash
curl http://localhost:8787/readyz
```

Response:
```json
{
  "service": "copium-proxy",
  "status": "healthy",
  "ready": true,
  "version": "0.5.21",
  "timestamp": "2026-04-10T16:36:25Z",
  "uptime_seconds": 12.483,
  "checks": {
    "startup": {"enabled": true, "ready": true, "status": "healthy"},
    "http_client": {"enabled": true, "ready": true, "status": "healthy"},
    "cache": {"enabled": true, "ready": true, "status": "healthy"},
    "rate_limiter": {"enabled": true, "ready": true, "status": "healthy"},
    "memory": {"enabled": false, "ready": true, "status": "disabled"}
  }
}
```

`/readyz` returns HTTP 503 when Copium has not completed startup or a required enabled subsystem is unavailable. This is the endpoint used by the container health checks.

### Aggregate Health

```bash
curl http://localhost:8787/health
```

Response:
```json
{
  "status": "healthy",
  "ready": true,
  "version": "0.5.21",
  "config": {
    "backend": "anthropic",
    "optimize": true,
    "cache": true,
    "rate_limit": true
  },
  "checks": {
    "startup": {"enabled": true, "ready": true, "status": "healthy"},
    "http_client": {"enabled": true, "ready": true, "status": "healthy"}
  }
}
```

### Detailed Statistics

```bash
curl http://localhost:8787/stats
```

`/stats` remains the live/session-oriented endpoint and now also includes a
`persistent_savings` block with durable proxy compression lifetime totals plus a
small recent preview. The existing `savings_history` field is still present and
remains session-scoped for backward compatibility.

For providers that return cache-write TTL bucket usage, `/stats` also includes
observed TTL breakdowns under `prefix_cache`:

- `observed_ttl_buckets.5m.tokens`
- `observed_ttl_buckets.1h.tokens`
- `observed_ttl_mix`

These are provider-reported observations, not configured TTL and not remaining
expiration time.

### Historical Savings

```bash
curl http://localhost:8787/stats-history
```

`/stats-history` exposes durable proxy compression history for dashboards and
other Copium frontends. It returns:

- lifetime proxy compression totals
- compact checkpoint history by default, with `history_mode=full` available for
  export/debug flows
- derived hourly, daily, weekly, and monthly rollups for charts
- a `history_summary` block describing stored versus returned checkpoint counts
- UTC timestamps throughout

By default the proxy stores this history at
`${COPIUM_WORKSPACE_DIR}/proxy_savings.json` (i.e.
`~/.copium/proxy_savings.json` when `COPIUM_WORKSPACE_DIR` is unset).
Set `COPIUM_SAVINGS_PATH` to override the location directly, or set
`COPIUM_WORKSPACE_DIR` to relocate the full state root. See the
[Filesystem Contract](filesystem-contract.md).

`/dashboard` uses this endpoint directly for its historical view, including the
daily/weekly/monthly rollups and built-in JSON / CSV export buttons.

```bash
curl "http://localhost:8787/stats-history?format=csv&series=weekly"
curl "http://localhost:8787/stats-history?format=csv&series=monthly"
curl "http://localhost:8787/stats-history?history_mode=full"
```

### Prometheus Metrics

```bash
curl http://localhost:8787/metrics
```

`/metrics` remains the built-in Prometheus-formatted operational view. The proxy now also emits the same operational events through the OTEL facade when OTEL metrics are configured.

### LLM APIs

The proxy supports both Anthropic and OpenAI API formats:

```bash
# Anthropic format
POST /v1/messages

# OpenAI format
POST /v1/chat/completions
```

### `POST /v1/compress`

Compression-only endpoint. Compresses messages without calling any LLM. Used by the [TypeScript SDK](typescript-sdk.md) and any HTTP client that wants compression as a service.

**Request:**
```json
{
  "messages": [...],     // OpenAI chat format
  "model": "gpt-4o"     // model name (for token counting)
}
```

**Response:**
```json
{
  "messages": [...],            // compressed messages
  "tokens_before": 15000,
  "tokens_after": 3500,
  "tokens_saved": 11500,
  "compression_ratio": 0.23,
  "transforms_applied": ["router:smart_crusher:0.35"],
  "ccr_hashes": ["a1b2c3"]
}
```

**Headers:**
- `x-copium-bypass: true` — skip compression, return messages as-is

**Error responses:** 400 (missing fields), 401 (bad API key), 503 (compression failed)

## Using with Claude Code

```bash
# Start proxy
copium proxy --port 8787

# In another terminal
ANTHROPIC_BASE_URL=http://localhost:8787 claude
```

## Using with Cursor

1. Start the proxy: `copium proxy`
2. In Cursor settings, set the base URL to `http://localhost:8787`

## Using with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8787/v1",
    api_key="your-api-key",  # Still needed for upstream
)
```

## Features

### ML Compression (Opt-In, Kompress)

> The earlier LLMLingua-2 integration documented in this section
> (`--llmlingua`, `--llmlingua-device`, `--llmlingua-rate`,
> `copium-ai[llmlingua]`, `LLMLinguaCompressor`) was retired and
> replaced by **Kompress** (ModernBERT). Install with `pip install
> 'copium-ai[ml]'`. See [transforms.md](transforms.md) and
> [ARCHITECTURE.md](ARCHITECTURE.md) for current configuration.

### Semantic Caching

The proxy caches responses for repeated queries:

- LRU eviction with configurable max entries
- TTL-based expiration
- Cache key based on message content hash

### Rate Limiting

Token bucket rate limiting protects against runaway costs:

- Configurable requests per minute
- Configurable tokens per minute
- Per-API-key tracking

### Cost Tracking

Track spending and enforce budgets:

- Real-time cost estimation
- Budget periods: hourly, daily, monthly
- Automatic request rejection when over budget

### Prometheus Metrics

Export metrics for monitoring:

```
copium_requests_total
copium_tokens_saved_total
copium_cost_usd_total
copium_latency_ms_sum
```

## Configuration via Environment

```bash
export COPIUM_HOST=0.0.0.0
export COPIUM_PORT=8787
export COPIUM_BUDGET=100.0

# Route OpenAI passthrough requests to a custom endpoint
export OPENAI_TARGET_API_URL=https://custom.openai.endpoint.com

# Route Anthropic passthrough requests to a custom endpoint
export ANTHROPIC_TARGET_API_URL=https://litellm.company.internal

copium proxy
```

## Running in Production

For production deployments:

```bash
# Use a process manager
pip install gunicorn

# Run with gunicorn
gunicorn copium.proxy.server:app \
  --workers 4 \
  --bind 0.0.0.0:8787 \
  --worker-class uvicorn.workers.UvicornWorker
```

Or with Docker:

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install "copium-ai[proxy]" \
    && apt-get purge -y build-essential && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
EXPOSE 8787
CMD ["copium", "proxy", "--host", "0.0.0.0"]
```

> **Note:** `build-essential` is required at install time because `copium-ai` includes `hnswlib`, a C++ extension that must be compiled from source. It is removed after installation to keep the image slim.
