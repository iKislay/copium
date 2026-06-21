# Copium Threat Model

> Last updated: 2026-06-21

## Security Principles

1. **Local-first**: No data leaves your machine except to your LLM providers
2. **No credential storage**: API keys are passed through, never persisted
3. **Reversible compression**: Originals stored locally in CCR, never sent to third parties
4. **Input validation**: All tool outputs validated before compression
5. **Telemetry off by default**: Anonymous stats only sent with explicit opt-in

## Assets

| Asset | Location | Protection |
|-------|----------|------------|
| User prompts and code | Memory only | Never persisted by Copium |
| API keys | Environment variables | Passed through, never logged |
| Compressed context | `~/.copium/ccr_store.sqlite` | Filesystem permissions |
| Compression metadata | `~/.copium/` | Filesystem permissions |

## Threat Actors

### 1. Malicious Tool Outputs
- **Attack**: Prompt injection via compressed tool outputs
- **Mitigation**: Input validation, optional semantic integrity checks
- **Status**: Research in progress (CompressionAttack paper)

### 2. Network Attacker (MITM)
- **Attack**: Intercept traffic between proxy and LLM
- **Mitigation**: TLS to provider APIs (default), localhost-only proxy
- **Status**: Addressed by provider SDK TLS

### 3. Compromised Dependency
- **Attack**: Malicious code in dependencies
- **Mitigation**: Pinned versions, cargo audit, pip-audit
- **Status**: CI automation in place

## Known Limitations

1. **CCR store is unencrypted at rest**: SQLite file relies on filesystem permissions
2. **Proxy listens on localhost**: No authentication by default
3. **Compression amplification**: May amplify certain prompt injection patterns

## Recommended Deployment

### Development (Default)
```bash
copium proxy  # Listens on localhost:8787
```
- Localhost-only access
- Filesystem permissions protect CCR store
- Suitable for personal use

### Production
```bash
# Add authentication layer (nginx, cloud LB)
# Use COPIUM_STATELESS=true for containerized deployments
# Enable Prometheus metrics for monitoring
```

### Enterprise
- Use COPIUM_LICENSE_KEY for managed deployments
- Enable enterprise security plugin if available
- Audit logs via COPIUM_LOG_FILE

## Security Checklist

- [ ] Proxy running on localhost only (default)
- [ ] `~/.copium/` directory has restrictive permissions (700)
- [ ] API keys in environment variables, not config files
- [ ] Telemetry disabled unless explicitly needed
- [ ] CCR store backed up regularly
- [ ] Dependencies audited (`cargo audit`, `pip-audit`)
