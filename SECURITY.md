# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :x:                |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

### How to Report

**Please DO NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email us at: **security@copium.dev**

Include the following information:
- Type of vulnerability (e.g., injection, data exposure, authentication bypass)
- Full path of the affected source file(s)
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact assessment

### What to Expect

1. **Acknowledgment**: We will acknowledge receipt within 48 hours
2. **Assessment**: We will assess the vulnerability and determine its severity
3. **Updates**: We will keep you informed of our progress
4. **Resolution**: We aim to resolve critical issues within 7 days
5. **Credit**: With your permission, we will credit you in the security advisory

### Security Best Practices for Users

When using Copium:

1. **API Keys**: Never commit API keys. Use environment variables.
2. **Proxy Exposure**: Don't expose the proxy server to the public internet without authentication
3. **Log Files**: Be aware that request logs may contain sensitive information
4. **Budget Limits**: Set budget limits to prevent unexpected costs
5. **Filesystem Permissions**: Protect `~/.copium/` directory (contains CCR store)
   ```bash
   chmod 700 ~/.copium
   ```
6. **Telemetry**: Disabled by default. Enable only if you want to contribute anonymous stats.
7. **Dependencies**: Regularly audit dependencies
   ```bash
   cargo audit
   pip-audit
   ```

### Scope

The following are in scope for security reports:
- Copium Python package (`pip install copium`)
- Copium proxy server
- Official integrations (LangChain, MCP)

The following are out of scope:
- Third-party integrations not maintained by us
- Issues in dependencies (report these to the upstream project)
- Social engineering attacks

## Security Features

Copium includes several security features:

- **No credential storage**: We never store or log API keys
- **Passthrough mode**: Sensitive content passes through unchanged by default
- **Input validation**: All inputs are validated before processing
- **Safe defaults**: Security-conscious defaults out of the box
- **Telemetry off by default**: Your data stays local unless you opt in

## Threat Model

For detailed security analysis, see [docs/security/threat-model.md](docs/security/threat-model.md).

Thank you for helping keep Copium and its users safe!
