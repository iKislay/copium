# 016. Observability

**Status:** done

## Telemetry

### Metrics

Copium exposes Prometheus metrics at `/metrics`.

**Key Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `copium_requests_total` | Counter | Total requests |
| `copium_tokens_original` | Counter | Original token count |
| `copium_tokens_compressed` | Counter | Compressed token count |
| `copium_savings_percent` | Histogram | Savings distribution |
| `copium_cache_hits_total` | Counter | Cache hits |
| `copium_cache_misses_total` | Counter | Cache misses |
| `copium_compression_duration_seconds` | Histogram | Compression latency |
| `copium_request_duration_seconds` | Histogram | Total request latency |

**Prometheus scrape config:**
```yaml
scrape_configs:
  - job_name: 'copium'
    static_configs:
      - targets: ['localhost:8787']
    metrics_path: '/metrics'
```

---

### Tracing

OpenTelemetry tracing support.

**Configuration (Langfuse):**
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
COPIUM_LANGFUSE_ENABLED=1
# Optional: override endpoint and service name
# LANGFUSE_BASE_URL=https://cloud.langfuse.com
# COPIUM_LANGFUSE_SERVICE_NAME=copium
```

**Spans:**
| Span | Description |
|------|-------------|
| `copium.proxy.request` | Full request lifecycle |
| `copium.compression` | Compression operation |
| `copium.cache.lookup` | Cache check |
| `copium.provider.call` | Provider API call |

---

### Logging

**Log Levels:**

| Level | Use Case |
|-------|----------|
| `DEBUG` | Detailed debugging |
| `INFO` | General operation |
| `WARNING` | Degraded operation |
| `ERROR` | Failures |

**Log Format (JSON):**
```json
{
  "timestamp": "2026-04-16T12:00:00Z",
  "level": "INFO",
  "message": "Request completed",
  "request_id": "abc123",
  "savings": 0.45,
  "duration_ms": 120
}
```

**Configuration:**
```bash
# Logging level is controlled via the --log-level CLI flag (copium proxy --log-level debug)
# or RUST_LOG env var for the Rust proxy. No COPIUM_LOG_LEVEL env var exists.
```

Or in config:
```yaml
logging:
  level: INFO
  format: json
```

---

## Dashboard

**URL:** `http://localhost:8787/dashboard`

**Metrics Shown:**
- Total savings over time
- Requests per day
- Cache hit rate
- Top compressed endpoints
- Session overview

**Requires:** the proxy process to be running. The dashboard is served by default at `/dashboard`.

---

## Alerting

### Recommended Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| HighErrorRate | error_rate > 5% | warning |
| LowSavings | savings < 20% | warning |
| CacheDown | cache_hits < 10% for 1h | critical |
| ProxyDown | health check fails | critical |

**Alert rule example (Prometheus):**
```yaml
groups:
  - name: copium
    rules:
      - alert: HighErrorRate
        expr: rate(copium_errors_total[5m]) / rate(copium_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate in Copium"
```

---

## Health Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/livez` | GET | Liveness check (process alive) |
| `/readyz` | GET | Readiness check (can serve traffic) |

**Health response:**
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

**Readiness response:**
```json
{
  "ready": true,
  "checks": {
    "database": true,
    "cache": true,
    "provider": true
  }
}
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-draft | 2026-04-16 | Initial observability document |
