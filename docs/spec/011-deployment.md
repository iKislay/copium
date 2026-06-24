# 011. Deployment

**Status:** done

## Deployment Profiles

### Docker Profile

**Image:** `copium-ai/copium:latest`

**Dockerfile:**
```dockerfile
FROM python:3.12-slim

RUN pip install copium-ai

EXPOSE 8787

ENTRYPOINT ["copium", "proxy"]
CMD ["--host", "0.0.0.0", "--port", "8787"]
```

**docker-compose.yml:**
```yaml
version: '3.8'
services:
  copium:
    image: copium-ai/copium:latest
    ports:
      - "8787:8787"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - COPIUM_MODE=token
    volumes:
      - copium-data:/root/.copium

volumes:
  copium-data:
```

**Run:**
```bash
docker-compose up -d
```

---

### Daemon Profile (recommended for daily use)

Start the proxy in the background — it detaches from the terminal and survives shell exit.

```bash
copium start               # start background daemon on port 8787
copium status              # check health, uptime, today's savings
copium stop                # stop gracefully (prints session summary)
copium restart             # restart to pick up config changes
```

Flags:

```bash
copium start --port 9090          # custom port
copium start --preset aggressive  # aggressive compression preset
copium start --memory             # enable persistent memory
copium start --no-wait            # fire-and-forget (don't wait for ready)
```

PID file: `~/.copium/deploy/default/runner.pid`  
Logs: `~/.copium/deploy/default/runner.log`

---

### System Service Profile (auto-start on login)

For users who want the proxy available before they open a terminal:

```bash
copium service install        # install as systemd (Linux) / launchd (macOS) / sc.exe (Windows)
copium service status         # show service health
copium service logs           # tail service logs (journalctl on Linux)
copium service logs -f        # follow logs continuously
copium service remove         # uninstall the service
```

| Platform | Mechanism | Config location |
|---|---|---|
| Linux | systemd user unit | `~/.config/systemd/user/copium.service` |
| macOS | launchd LaunchAgent | `~/Library/LaunchAgents/com.copium.default.plist` |
| Windows | Windows Service / Task Scheduler | via `sc.exe` or `schtasks` |

---

### Native Profile (foreground / manual)

**Run (blocks the terminal):**
```bash
copium proxy --host 0.0.0.0 --port 8787
```


### Embedded Profile

**Usage:**
```python
from copium import CopiumClient

client = CopiumClient(
    api_key="your-api-key",
    base_url="http://localhost:8787"
)

result = await client.compress(messages)
```

---

## Cloud Presets

### AWS (EC2/ECS)

```yaml
# ~/.copium/config.yaml
deployment:
  profile: aws
  instance_type: t3.medium

compression:
  enabled: true
  max_tokens: 8192

cache:
  backend: redis
  redis_url: redis://localhost:6379
```

### Google Cloud (Cloud Run)

```yaml
deployment:
  profile: gcp
  region: us-central1
  memory: 512Mi
  cpu: 1
```

### Azure (Container Apps)

```yaml
deployment:
  profile: azure
  resource_group: copium-rg
```

---

## Runtime Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COPIUM_MODE` | `token` | Proxy mode (`token` or `cache`) |
| `COPIUM_PORT` | `8787` | Proxy port |
| `COPIUM_HOST` | `127.0.0.1` | Proxy host |
| `ANTHROPIC_API_KEY` | - | Anthropic API key |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `COPIUM_TELEMETRY` | enabled | Set to `off` to disable telemetry |

### Config File

```yaml
# ~/.copium/config.yaml
proxy:
  host: 0.0.0.0
  port: 8787

compression:
  enabled: true
  max_tokens: 4096
  overlap_tokens: 512
  content_sensitivity: 0.5
  preserve_system_messages: true
  priority_tokens: 1024

cache:
  enabled: true
  ttl: 3600
  max_size: 10000

telemetry:
  metrics:
    enabled: true
  tracing:
    enabled: false

learn:
  enabled: false
```

---

## Resource Requirements

| Deployment | CPU | Memory | Storage |
|------------|-----|--------|---------|
| Minimal | 0.5 core | 512MB | 1GB |
| Default | 1 core | 1GB | 5GB |
| Enterprise | 2 cores | 2GB | 20GB |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-draft | 2026-04-16 | Initial deployment document |
