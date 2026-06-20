# 017. Operations

**Status:** done

## Health Endpoints

### `GET /health`

Basic health check. Returns 200 if process is running.

```bash
curl http://localhost:8787/health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

---

### `GET /livez`

Liveness check. Returns 200 if process is alive.

```bash
curl http://localhost:8787/livez
```

---

### `GET /readyz`

Readiness check. Returns 200 if ready to serve traffic.

```bash
curl http://localhost:8787/readyz
```

**Response:**
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

## Logs

### Log Locations

| Installation | Location |
|-------------|----------|
| Docker | `docker logs copium` |
| Native | `~/.copium/logs/` |
| Systemd | `journalctl -u copium` |

### Log Levels

Set via CLI flag or `RUST_LOG` env var for the Rust proxy:
```bash
# Python proxy
copium proxy --log-level debug

# Rust proxy
RUST_LOG=debug copium-proxy --upstream http://...
```

---

## Metrics

### Prometheus

**Scrape Config:**
```yaml
scrape_configs:
  - job_name: 'copium'
    static_configs:
      - targets: ['localhost:8787']
    metrics_path: '/metrics'
```

---

## Upgrade Procedure

### Docker

```bash
docker pull copium-ai/copium:latest
docker-compose down
docker-compose up -d
```

### Native

```bash
pip install --upgrade copium-ai
# Restart copium service
```

### Embedded

```bash
pip install --upgrade copium-ai
# Restart application
```

---

## Rollback

### Docker

```bash
docker-compose down
docker tag copium-ai/copium:latest copium-ai/copium:rollback
# Edit docker-compose.yml to use rollback tag
docker-compose up -d
```

---

## Monitoring

### Key Metrics to Watch

1. **Request rate** — requests per second
2. **Error rate** — 4xx + 5xx / total
3. **Savings rate** — average savings percentage
4. **Latency** — p50, p95, p99
5. **Cache hit rate** — hits / total

**Prometheus queries:**
```promql
# Request rate
rate(copium_requests_total[5m])

# Error rate
rate(copium_errors_total[5m]) / rate(copium_requests_total[5m])

# Average savings
rate(copium_tokens_original[5m] - copium_tokens_compressed[5m]) / rate(copium_tokens_original[5m])

# Cache hit rate
rate(copium_cache_hits_total[5m]) / (rate(copium_cache_hits_total[5m]) + rate(copium_cache_misses_total[5m]))
```

---

## Runbook

| Symptom | Cause | Solution |
|---------|-------|----------|
| "Connection refused" | Proxy not running | Start it with `copium proxy` |
| "Cache miss on every request" | Cache disabled | Start without `--no-cache` |
| "No savings shown" | Database locked | Check file permissions |
| "Provider timeout" | Network issue | Check firewall/proxy |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-draft | 2026-04-16 | Initial operations document |
