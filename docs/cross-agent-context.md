# Cross-Agent Context Sharing

Copium provides the missing **context layer for multi-agent systems**. When agents hand off to each other—across frameworks, sessions, or tools—context gets lost. SharedContext fixes this by compressing, persisting, and making context searchable.

## The Problem

| Tool | Context Scope | What's Lost |
|------|---------------|-------------|
| Claude Code | Single session | Everything from previous sessions |
| Cursor | Per-window | Other windows, other editors |
| Aider | Per-session | Previous sessions, other tools |
| CrewAI | Per-crew run | Previous runs, other crews |

Multi-agent architectures deliver 2-4x performance gains, but context handoff taxes erase those gains. Without shared context, you spend more tokens re-explaining than you save by decomposing.

## Solution: SharedContext

```python
from copium import SharedContext

# Persistent mode — survives process restarts
ctx = SharedContext(persistent=True)

# Agent A stores output (80% compression)
ctx.put("research", big_research_output, agent="researcher")

# Agent B gets compressed version
summary = ctx.get("research")

# Agent B needs full details on demand
full = ctx.get("research", full=True)
```

## Architecture

```
Agent A (Researcher)
    │
    ├── put("research", output, agent="researcher")
    │       │
    │       ▼
    │   PersistentSharedContext
    │   ├── Compresses via Copium pipeline
    │   ├── Stores in SQLite (persistent)
    │   ├── Tracks agent provenance
    │   ├── Resolves conflicts
    │   ├── Logs to audit trail
    │   └── TTL-based expiration
    │
    ▼
Agent B (Coder)
    │
    ├── get("research")      → 4K tokens (compressed)
    ├── get("research", full=True) → 20K tokens (original)
    └── search("findings")   → Semantic search results
```

## Features

### Persistent Storage

SQLite-backed with WAL mode for concurrent reads. Data stored in `~/.copium/shared_context.db`.

```python
ctx = SharedContext(persistent=True, project_id="my-app")
```

### Conflict Resolution

When multiple agents write to the same key:

```python
from copium.shared_context import PersistentSharedContext, ConflictStrategy

ctx = PersistentSharedContext(
    conflict_strategy=ConflictStrategy.HIGHEST_CONFIDENCE,
)
```

Strategies: `LAST_WRITE_WINS`, `HIGHEST_CONFIDENCE`, `AGENT_PRIORITY`, `MERGE`, `KEEP_BOTH`

### Semantic Search

```python
results = ctx.search("authentication middleware", top_k=5)
for r in results:
    print(f"[{r.similarity:.2f}] {r.key} (by {r.agent})")
```

### Agent Provenance

Every entry tracks who created it:

- Agent name and provider
- Model used
- Session and user IDs
- Confidence score
- Version history

### Audit Trail

All operations logged for enterprise compliance:

```python
records = ctx.audit_log.query(agent_name="researcher", limit=20)
```

## Framework Integrations

### CrewAI

```python
from copium.integrations.crewai import CopiumCrewContext

ctx = CopiumCrewContext(persistent=True)
ctx.store_task_output("research", output, agent_role="Researcher")
compressed = ctx.get_context_for_task("research")
```

### LangGraph

```python
from copium.integrations.langchain.shared_context import CopiumSharedContext

ctx = CopiumSharedContext(persistent=True)
ctx.store("research", result, agent="researcher")
research = ctx.retrieve("research")
```

### OpenAI Agents SDK

```python
from copium.integrations.openai_agents import CopiumHandoff

handoff = CopiumHandoff(persistent=True)
compressed = handoff.handoff_context("Researcher", "Coder", output)
```

### AutoGen

```python
from copium.integrations.autogen import SharedContextMiddleware

middleware = SharedContextMiddleware(persistent=True)
middleware.on_message("researcher", output)
enriched = middleware.enrich_message("coder", message)
```

### Agno

```python
from copium.integrations.agno.shared_context import CopiumAgnoTeam

team = CopiumAgnoTeam(persistent=True)
team.store_output("researcher", output)
context = team.get_context_for("coder")
```

### Strands

```python
from copium.integrations.strands.shared_context import CopiumStrandsContext

ctx = CopiumStrandsContext(persistent=True)
ctx.store("analysis", result, agent="analyzer")
```

## Zero-Code Integration (Proxy Mode)

Any agent routing through the Copium proxy automatically shares context — no code changes needed:

```bash
copium proxy --memory

export ANTHROPIC_BASE_URL=http://localhost:8082
export OPENAI_API_BASE=http://localhost:8082/v1

# All agents now share compressed context + persistent memory
```

## Performance

| Metric | Target |
|--------|--------|
| Compression ratio | ≥ 75% |
| Write latency (P99) | < 15ms |
| Read latency (P99) | < 10ms |
| Vector search (P99) | < 20ms |

## Module Structure

```
copium/shared_context/
├── __init__.py              # PersistentSharedContext orchestrator
├── persistent_store.py      # SQLite-backed storage
├── vector_index.py          # Cosine similarity search
├── serializer.py            # Content serialization
├── eviction.py              # TTL + LRU eviction policies
├── provenance.py            # Agent identity tracking
├── conflict_resolver.py     # Write conflict strategies
└── audit_log.py             # Operation audit trail
```
