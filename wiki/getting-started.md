# Getting Started with Copium

This guide will help you get up and running with Copium in under 5 minutes.

## Installation

**Python:**

```bash
# Core package (minimal dependencies)
pip install copium

# With proxy server
pip install copium[proxy]

# With semantic relevance (for smarter compression)
pip install copium[relevance]

# Everything
pip install copium[all]
```

**TypeScript / Node.js:**

```bash
npm install copium-ai
```

**Docker-native:**

```bash
curl -fsSL https://raw.githubusercontent.com/iKislay/copium/main/scripts/install.sh | bash
```

PowerShell:

```powershell
irm https://raw.githubusercontent.com/iKislay/copium/main/scripts/install.ps1 | iex
```

See [Docker-native install](docker-install.md) for wrapper behavior, compose usage, and host-integrated `wrap` flows.

If you want Copium to stay up in the background and automatically serve supported tools, use [Persistent Installs](persistent-installs.md):

```bash
copium install apply --preset persistent-service --providers auto
```

## Quick Start: Proxy Mode (Recommended)

The easiest way to use Copium is as a proxy server:

```bash
# Start the proxy
copium proxy --port 8787
```

Then point your LLM client at it:

```bash
# Claude Code
ANTHROPIC_BASE_URL=http://localhost:8787 claude

# GitHub Copilot CLI (default Anthropic-style proxy route)
copium wrap copilot -- --model claude-sonnet-4-20250514

# OpenAI-compatible clients
OPENAI_BASE_URL=http://localhost:8787/v1 your-app
```

That's it! All your requests now go through Copium and get optimized automatically.

## Quick Start: Python SDK

If you want programmatic control:

```python
from copium import CopiumClient
from openai import OpenAI

# Create a wrapped client
client = CopiumClient(
    original_client=OpenAI(),
    default_mode="optimize",
)

# Use exactly like the original
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ],
)
```

## Modes

### Audit Mode

Observe without modifying:

```python
client = CopiumClient(
    original_client=OpenAI(),
    default_mode="audit",
)
# Logs metrics but doesn't change requests
```

### Optimize Mode

Apply transforms to reduce tokens:

```python
client = CopiumClient(
    original_client=OpenAI(),
    default_mode="optimize",
)
# Compresses tool outputs, aligns cache prefixes, etc.
```

### Simulate Mode

Preview what optimizations would do:

```python
plan = client.chat.completions.simulate(
    model="gpt-4o",
    messages=[...],
)
print(f"Would save {plan.tokens_saved} tokens")
print(f"Transforms: {plan.transforms_applied}")
```

## Next Steps

- [Proxy Server Documentation](proxy.md) - Configure the proxy
- [Transforms Reference](transforms.md) - Understand each transform
- [API Reference](api.md) - Full API documentation
