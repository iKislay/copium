# Cross-Agent Context Sharing

Copium is the **context layer for multi-agent systems**. Compress what moves between agents, persist it across sessions, make it searchable. Any framework. Any provider. Zero code changes.

## Why

Multi-agent architectures deliver 2-4x performance gains over single-agent. But the context handoff tax erases those gains:

- **Intra-workflow loss**: Context between agents in the same workflow is lost at each handoff
- **Inter-session loss**: Context from previous sessions is completely gone
- **Cross-tool loss**: Context between tools (Claude Code + Cursor) is siloed

## Quick Start

```python
from copium import SharedContext

# Enable persistent mode for cross-session sharing
ctx = SharedContext(persistent=True)

# Agent A stores large output (auto-compressed)
ctx.put("research", big_research_output, agent="researcher")

# Agent B gets compressed version (~80% smaller)
summary = ctx.get("research")

# Agent B needs full details on demand
full = ctx.get("research", full=True)

# Semantic search across all shared context
results = ctx.search("database migration findings", top_k=5)
```

## Features

| Feature | Description |
|---------|-------------|
| **Persistent Storage** | SQLite-backed, survives proxy restarts |
| **Conflict Resolution** | 5 strategies for concurrent writes |
| **Semantic Search** | Vector-based search over all entries |
| **Agent Provenance** | Track who wrote what, when |
| **Audit Trail** | Full operation log for compliance |
| **Framework Integrations** | CrewAI, LangGraph, OpenAI Agents, AutoGen, Agno, Strands |
| **Zero-Code Mode** | Proxy-based, no code changes needed |

## Detailed Documentation

See the full guide at `guides/shared-context.md` for:

- Configuration options
- Conflict resolution strategies
- Framework-specific integration examples
- Proxy mode setup
- API reference
