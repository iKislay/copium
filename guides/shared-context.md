# SharedContext — Compressed Inter-Agent Context Sharing

When agents hand off to each other, context gets replayed in full. SharedContext compresses what moves between agents using Copium's compression pipeline.

## Quick Start

```python
from copium import SharedContext

ctx = SharedContext()

# Agent A stores large output
ctx.put("research", big_research_output, agent="researcher")

# Agent B gets compressed version (~80% smaller)
summary = ctx.get("research")

# Agent B needs full details
full = ctx.get("research", full=True)
```

## API

### `put(key, content, *, agent=None)`

Store content under a key. Compresses automatically using Copium's full pipeline (SmartCrusher for JSON, CodeCompressor for code, Kompress for text).

```python
entry = ctx.put("findings", big_json_output, agent="researcher")

entry.original_tokens     # 20,000
entry.compressed_tokens   # 4,000
entry.savings_percent     # 80.0
entry.transforms          # ["router:json:0.20"]
```

### `get(key, *, full=False)`

Retrieve content. Returns compressed version by default, original with `full=True`.

```python
compressed = ctx.get("findings")           # 4K tokens
original = ctx.get("findings", full=True)  # 20K tokens
missing = ctx.get("nonexistent")           # None
```

### `get_entry(key)`

Get the full `ContextEntry` with metadata.

```python
entry = ctx.get_entry("findings")
entry.key                # "findings"
entry.agent              # "researcher"
entry.original_tokens    # 20000
entry.compressed_tokens  # 4000
entry.savings_percent    # 80.0
entry.timestamp          # 1710000000.0
entry.transforms         # ["router:json:0.20"]
```

### `keys()`

List all non-expired keys.

### `stats()`

Aggregated stats across all entries.

```python
stats = ctx.stats()
stats.entries                  # 3
stats.total_original_tokens    # 60000
stats.total_compressed_tokens  # 12000
stats.total_tokens_saved       # 48000
stats.savings_percent          # 80.0
```

### `clear()`

Remove all entries.

## Configuration

```python
ctx = SharedContext(
    model="claude-sonnet-4-5-20250929",  # For token counting
    ttl=3600,                             # 1 hour (default)
    max_entries=100,                       # Evicts oldest when full
)
```

## Framework Examples

### CrewAI

```python
from copium import SharedContext

ctx = SharedContext()

# After researcher task
ctx.put("findings", researcher_task.output.raw)

# Coder task gets compressed context
coder_context = ctx.get("findings")
```

### LangGraph

```python
from copium import SharedContext

ctx = SharedContext()

def researcher_node(state):
    result = do_research()
    ctx.put("research", result)
    return {"research_summary": ctx.get("research")}

def coder_node(state):
    # Compressed summary in state, full details on demand
    full = ctx.get("research", full=True)
    return {"code": write_code(full)}
```

### OpenAI Agents SDK

```python
from copium import SharedContext

ctx = SharedContext()

def compress_handoff(messages):
    for msg in messages:
        if len(msg.content) > 1000:
            ctx.put(msg.id, msg.content)
            msg.content = ctx.get(msg.id)
    return messages

handoff(agent=coder, input_filter=compress_handoff)
```

### Any Framework

SharedContext is framework-agnostic. It's just `put()` and `get()`. Use it wherever context moves between agents.

## How It Works

Under the hood, `put()` calls `copium.compress()` (the same pipeline used by the proxy) and stores the original in memory. `get()` returns the compressed version. `get(full=True)` returns the original.

- JSON arrays → SmartCrusher (70-95% compression)
- Code → CodeCompressor (AST-aware, with `[code]` extra)
- Text → Kompress (ModernBERT, with `[ml]` extra) or passthrough
- Entries expire after TTL (default 1 hour)
- Oldest entries evicted when max_entries reached

---

## Persistent Mode (Cross-Session Sharing)

By default, SharedContext is in-memory only — entries are lost when the process exits. Enable **persistent mode** to survive restarts and share context across sessions:

```python
from copium import SharedContext

# Persistent mode — SQLite-backed, survives restarts
ctx = SharedContext(persistent=True)

ctx.put("research", big_output, agent="researcher")
# Entry persists in ~/.copium/shared_context.db

# Later, in a different session/process:
ctx2 = SharedContext(persistent=True)
summary = ctx2.get("research")  # Still available!
```

### Configuration

```python
ctx = SharedContext(
    persistent=True,
    model="claude-sonnet-4-5-20250929",
    ttl=3600,
    max_entries=1000,
    project_id="my-app",  # Isolate by project
)
```

### Conflict Resolution

When multiple agents write to the same key, configurable strategies determine the winner:

```python
from copium.shared_context import PersistentSharedContext, ConflictStrategy

ctx = PersistentSharedContext(
    conflict_strategy=ConflictStrategy.HIGHEST_CONFIDENCE,
)

# Agent A writes with confidence 0.8
ctx.put("analysis", output_a, agent="analyst_a", confidence=0.8)

# Agent B writes with confidence 0.9 — wins!
ctx.put("analysis", output_b, agent="analyst_b", confidence=0.9)
```

Available strategies:
- `LAST_WRITE_WINS` — Most recent update wins (default)
- `HIGHEST_CONFIDENCE` — Highest confidence score wins
- `AGENT_PRIORITY` — Predefined agent hierarchy
- `MERGE` — Combine both (supports custom merge_fn for LLM merge)
- `KEEP_BOTH` — Retain both entries

### Semantic Search

Search across all shared context using natural language:

```python
results = ctx.search("database migration findings", top_k=5)
for r in results:
    print(f"[{r.similarity:.2f}] {r.key} (by {r.agent})")
```

### Audit Trail

All operations are logged for enterprise compliance:

```python
from copium.shared_context import PersistentSharedContext

ctx = PersistentSharedContext(audit=True)
# All put/get/search/delete operations logged to shared_context_audit.db

# Query audit history
records = ctx.audit_log.query(agent_name="researcher", limit=20)
```

### Agent Provenance

Track which agent created/modified each entry:

```python
from copium.shared_context import AgentIdentity

# Headers extracted automatically in proxy mode:
# X-Copium-Agent: researcher
# X-Copium-Agent-Provider: anthropic
# X-Copium-Agent-Model: claude-sonnet-4-5-20250929
```

---

## Framework Integrations

### CrewAI

```python
from copium.integrations.crewai import CopiumCrewContext, CopiumCrewCallbacks

ctx = CopiumCrewContext(persistent=True)
callbacks = CopiumCrewCallbacks(ctx)

# After task completes
callbacks.on_task_complete("research", output, agent_role="Researcher")

# Before next task, get context prefix
prefix = callbacks.get_context_prefix("coding")
```

### LangGraph

```python
from copium.integrations.langchain.shared_context import (
    CopiumSharedContext,
    create_shared_context_store_node,
)

ctx = CopiumSharedContext(persistent=True)

def researcher_node(state):
    result = do_research()
    ctx.store("research", result, agent="researcher")
    return {"messages": [result]}

def coder_node(state):
    research = ctx.retrieve("research")
    return {"messages": [write_code(research)]}
```

### OpenAI Agents SDK

```python
from copium.integrations.openai_agents import CopiumHandoff

handoff = CopiumHandoff(persistent=True)

# One-call handoff between agents
compressed = handoff.handoff_context(
    from_agent="Researcher",
    to_agent="Coder",
    content=researcher_output,
)
```

### AutoGen

```python
from copium.integrations.autogen import SharedContextMiddleware

middleware = SharedContextMiddleware(persistent=True)

# Capture output
middleware.on_message("researcher", researcher_output)

# Inject into next agent's message
enriched = middleware.enrich_message("coder", original_message)
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
analysis = ctx.retrieve("analysis")
```

---

## Zero-Code Integration (Proxy Mode)

The most powerful integration requires **zero code changes**. Any agent routing through the Copium proxy automatically shares context:

```bash
# Start proxy with memory + shared context
copium proxy --memory

# Point all agents at the proxy
export ANTHROPIC_BASE_URL=http://localhost:8082
export OPENAI_API_BASE=http://localhost:8082/v1

# Now Claude Code, Cursor, Aider, Codex all share:
# 1. Compressed context (SharedContext)
# 2. Persistent memory (Memory)
# 3. Agent provenance (tracked via headers)
```

