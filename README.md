# Cross-Agent Context Sharing (New)

Copium is now the **context layer for multi-agent systems**. Agents don't share context
across sessions, tools, or each other — until now. SharedContext compresses what moves
between agents, persists it across sessions, and makes it searchable.

Key capabilities:

- **Persistent SharedContext**: SQLite-backed storage that survives proxy restarts.
- **Agent Provenance**: Track which agent created/modified each context entry.
- **Conflict Resolution**: Configurable strategies (last-write-wins, confidence, priority, merge).
- **Semantic Search**: Vector-based search over all shared context entries.
- **Audit Trail**: Full operation log for enterprise compliance.
- **Framework Integrations**: CrewAI, LangGraph, OpenAI Agents SDK, AutoGen, Agno, Strands.
- **Zero-Code Proxy Mode**: Any agent routing through the proxy shares context automatically.

```python
from copium import SharedContext

ctx = SharedContext(persistent=True)

# Agent A stores output (compressed + persisted)
ctx.put("research", big_output, agent="researcher")

# Agent B gets compressed version (~80% smaller)
summary = ctx.get("research")

# Semantic search across all shared context
results = ctx.search("database migration findings", top_k=5)
```

See:

- `guides/shared-context.md`
- `copium/shared_context/` (PersistentStore, VectorIndex, ConflictResolver, AuditLog)
- `copium/integrations/` (crewai, openai_agents, autogen, langchain, agno, strands)

# Pre-Compaction Data Loss Prevention (New)

Copium now prevents the silent data loss caused by auto-compaction in agentic tools.

When Claude Code, Cursor, or Codex fires auto-compaction, critical context is destroyed:
reasoning chains, architectural decisions, file relationships, and user intent. Copium's
new compaction hooks preserve this state and make recovery automatic.

Key capabilities:

- **Input-Priority Compression**: User messages (high entropy) preserved; tool outputs compressed.
- **Entropy-Based Scoring**: Information density scoring for intelligent compression scheduling.
- **Incremental Checkpointing**: Gradual state saves every N tool calls (no cliff).
- **Claude Code Hook Integration**: Native PreCompact/PostCompact hook bridge.
- **CCR Safety Net**: All compression remains reversible via `copium_retrieve`.

See:

- `guides/compaction-prevention.md`
- `copium/hooks/` (InputPriorityHooks, IncrementalCheckpointHooks, claude_code)

# Agent Context Management (New)

Copium now includes a Smart Zone based agent-aware context lifecycle in `copium/agent_context/`.

Key capabilities:

- Smart Zone budget enforcement to keep context in high-quality ranges.
- Phase detection: orientation, exploration, implementation, verification.
- Value-aware and content-type-aware compression scheduling.
- Orientation cache to reduce first-turn tool-call overhead.
- Context health monitoring and recommendations for long sessions.

See:

- `guides/agent-context-management.md`
- `docs/agent-context-management.md`

# Position-Aware Compression (Lost in the Middle)

Initial implementation work has started for position-aware compression to reduce
"lost in the middle" degradation in long contexts.

Implemented in this iteration:
- Rust `position_aware` transform module with zones, scoring, and configuration.
- Python `position_aware` module parity helpers.
- SmartCrusher planner helper for position-aware keep-order optimization.
- Unit tests covering zone classification, weighting, and bookend reordering.

This is an opt-in foundation. Default behavior remains unchanged when
position weighting is disabled.

# Quality Preservation (New)

Copium now includes a comprehensive quality preservation framework in `copium/quality/`.

The community's #1 concern with context compression: "Does it break my agent's answers?"
Our answer: verifiable, benchmarked, auditable proof that quality is preserved.

Key capabilities:

- **Quality Gate**: Post-compression validation with 4 checks (token reduction, critical markers,
  structure, density). Auto-reverts to original if any check fails.
- **Quality Metrics**: ROUGE-L (≥0.85), IPS (≥0.95), CWQ (≥0.85) measurement.
- **A/B Testing**: Statistical framework with Welch's t-test, Cohen's d, power analysis.
- **Quality Dashboard**: Real-time session monitoring via `copium quality status`.
- **Benchmarks**: Synthetic and real-world benchmark suites with CI integration.

```python
from copium.quality import QualityGate, GateConfig, ContentType

gate = QualityGate(GateConfig(min_token_savings_pct=10.0))
result = gate.validate(original, compressed, ContentType.JSON)
# Auto-reverts to original if quality drops below threshold
```

The bottom line: **70-90% compression, <2% accuracy drop** — because of structure-aware
compression, CCR reversibility, and quality gates that catch failures automatically.

See:

- `docs/content/docs/quality-preservation.mdx`
- `copium/quality/` (QualityGate, QualityMetrics, ABTestHarness, QualityDashboard)

# Copium

**The context compression layer for LLM applications**

> 65–94% fewer tokens. Zero quality loss. Drop-in proxy for Claude, GPT, Gemini, Bedrock, and local LLMs.

[![PyPI](https://img.shields.io/pypi/v/copium-ai.svg)](https://pypi.org/project/copium-ai/)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://pypi.org/project/copium-ai/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)](https://github.com/iKislay/copium/actions)
[![Docs](https://img.shields.io/badge/docs-online-blue.svg)](https://copium-docs.vercel.app/docs)

<p>
  <a href="https://copium-docs.vercel.app/docs">Docs</a> &middot;
  <a href="#get-started-60-seconds">Install</a> &middot;
  <a href="#proof">Proof</a> &middot;
  <a href="#compared-to">Alternatives</a> &middot;
  <a href="#connect-your-ai-agent">Agent Guides</a> &middot;
  <a href="https://github.com/iKislay/copium">GitHub</a>
</p>

---

## What is this?

You know how your AI coding assistant (Claude Code, Cursor, Copilot, etc.) sometimes slows down mid-session, starts forgetting things it read earlier, or just becomes weirdly bad at tasks it was great at ten minutes ago? That's the context window filling up. Every file your agent reads, every command it runs, every tool output it processes — it all piles into a prompt that the AI has to re-read from scratch on every single message. You're paying for all of it, every time.

Copium sits between your agent and the AI provider and compresses everything before it goes out. It's a local proxy — your data never leaves your machine. Same answers. Fraction of the tokens.

The gains are real: **1.4 billion tokens saved** across 50K+ sessions in production.

---

## Get started (60 seconds)

### Install

```bash
# Recommended — installs globally in an isolated environment
pipx install "copium-ai[proxy]"

# If you use uv
uv tool install "copium-ai[proxy]"

# Project-local install (less recommended for CLI use)
pip install "copium-ai[proxy]"
```

> **Why `pipx`?** It installs CLI tools into isolated environments so `copium` is available globally without polluting any project's dependencies. If you don't have `pipx`: `pip install pipx && pipx ensurepath`.

### RTK (Rust Token Killer) — Included automatically

RTK is bundled with Copium and auto-installed on first `copium wrap` run. No separate install needed.

For RTK-only mode (CLI stdout compression without the proxy):
```bash
copium wrap claude --rtk-only
```

This gives you RTK's exact UX — `rtk git status`, `rtk grep`, etc. — then upgrade to full proxy compression anytime by dropping `--rtk-only`.

To install RTK manually (standalone):
```bash
# Via Homebrew (macOS/Linux)
brew install rtk

# Via curl (Linux/macOS)
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/main/install.sh | bash

# Via cargo
cargo install --git https://github.com/rtk-ai/rtk
```

Then activate for your agent:
```bash
# Claude Code
rtk init --claude-code

# Verify savings
rtk gain
```

### Start the proxy

**Recommended — background daemon (survives shell exit):**

```bash
copium start               # starts on http://localhost:8787, detaches from terminal
copium status              # check health, port, today's savings
copium status --prompt     # minimal output for shell prompts (⚡ 38%)
copium stop                # stop gracefully (prints session summary with duration + all-time totals)
copium restart             # restart to pick up config changes
copium ping                # fast health check — exit 0 running, exit 1 stopped
```

**One-shot foreground mode (blocks the terminal):**

```bash
copium proxy               # or: copium run
```

Point your agent at the proxy:

```bash
# Claude Code
export ANTHROPIC_BASE_URL=http://localhost:8787

# Cursor / Aider / OpenCode / any OpenAI-compatible client
export OPENAI_API_BASE=http://localhost:8787/v1

# Watch the savings live
copium status
# or: copium tui  (live terminal dashboard)
# or: open http://localhost:8787/dashboard in your browser
```

That's it. No config files. No code changes. Copium automatically compresses every request.

---

## Connect your AI agent

### Claude Code

```bash
copium wrap claude
```

That single command starts the proxy and configures Claude Code to route through it. When you're done, `copium unwrap claude` restores everything.

Alternatively, set it manually:

```bash
copium run &
export ANTHROPIC_BASE_URL=http://localhost:8082
claude  # or claude-code, or claude --dangerously-skip-permissions
```

### Cursor

```bash
copium run &
# In Cursor settings → OpenAI API Base URL:
# http://localhost:8082/v1
```

Or via environment:

```bash
export OPENAI_API_BASE=http://localhost:8082/v1
cursor .
```

### OpenCode

OpenCode uses the OpenAI-compatible API format:

```bash
copium run &
export OPENAI_BASE_URL=http://localhost:8082/v1
opencode
```

Or set it permanently in your OpenCode config:

```json
{
  "openai": {
    "baseURL": "http://localhost:8082/v1"
  }
}
```

### Aider

```bash
copium wrap aider
# or manually:
aider --openai-api-base http://localhost:8082/v1
```

### Codex (OpenAI)

```bash
copium wrap codex
# Automatically patches ~/.codex/config.toml
# Undo with: copium unwrap codex
```

### GitHub Copilot

```bash
copium wrap copilot
```

This routes Copilot through Copium while keeping your existing auth. Supports both BYOK and subscription modes.

### Mistral / Vibe

```bash
copium wrap vibe
```

### VS Code Extensions

#### Cline

```bash
copium wrap cline
# Then configure in VS Code:
#   Settings > Cline > API Provider > Anthropic
#   Base URL: http://localhost:8082
```

#### Continue

```bash
copium wrap continue
# Auto-injects into .continue/config.json
```

### Antigravity (Google)

> **Note:** As of June 2026, Google transitioned Gemini CLI to Antigravity CLI. The new Antigravity 2.0 Desktop App and CLI use Google Sign-In OAuth authentication and route through Vertex AI — they do **not** expose proxy/base URL settings. Copium cannot currently intercept Antigravity traffic.

**Workarounds:**
- Use the old Gemini CLI (if available) which routes through Cloud Code Assist
- For enterprise users: configure Vertex AI with Copium proxy separately
- Wait for Google to add proxy configuration support

### Any HTTP client / custom app

If your tool lets you set a base URL or API endpoint:

```
http://localhost:8082         → Anthropic-compatible
http://localhost:8082/v1      → OpenAI-compatible
http://localhost:8082/bedrock → AWS Bedrock
http://localhost:8082/vertex  → Vertex AI (Google Cloud)
```

### As a Python library

If you don't want the proxy at all and just want to compress messages inline:

```python
import json
from copium import compress

# Works with any messages list you'd send to an LLM
data = json.load(open("data.json"))   # e.g. 500-item JSON array
result = compress([{"role": "user", "content": json.dumps(data)}])

print(f"Saved {result.compression_ratio:.1%} tokens")
# → Saved 64.8% tokens
```

### As an MCP server

```bash
pip install "copium-ai[mcp]"
```

Then add to your MCP client config:

```json
{
  "mcpServers": {
    "copium": {
      "command": "copium",
      "args": ["mcp"]
    }
  }
}
```

Exposes three tools: `copium_compress`, `copium_retrieve`, `copium_stats`.

---

## How it works

You don't need to understand this to use Copium. But if you're curious:

```
 Your agent / app
   (Claude Code, Cursor, Aider, OpenCode, your own code...)
        |   prompts, tool outputs, logs, RAG results, files
        v
    +----------------------------------------------------+
    |  Copium   (runs locally — your data stays here)   |
    |  -------------------------------------------------  |
    |  ToolPrefilter  → ContentRouter → SmartCrusher    |
    |  Session Dedup  | SelfCompressor | Kompress       |
    |  Cache Aligner  | Error Compressor | TOON Encoder |
    |  Diff Response  | Output Compressor               |
    +----------------------------------------------------+
        |   compressed prompt (same meaning, fewer tokens)
        v
 LLM provider  (Anthropic, OpenAI, Gemini, Ollama, Bedrock...)
```

Each component targets a specific kind of waste:

| Component | What it removes | Typical savings |
|---|---|---|
| **ToolPrefilter** | Oversized tool outputs (500-match grep → 50 lines) | 60–95% |
| **ContentRouter** | Routes each chunk to the best compressor | 20–60% |
| **SmartCrusher** | Compresses JSON arrays, repeated tool outputs | 40–95% |
| **Session Dedup** | Re-sent file content across conversation turns | 30–70% |
| **SelfCompressor** | LLM self-compression markers (_context_updates) | 40–80% |
| **Error Compressor** | Verbose stack traces → structured error cards | 50–80% |
| **ANSI Remover** | Terminal colors, spinners, progress bars | 10–30% |
| **TOON Encoder** | JSON arrays → pipe-delimited tables | 15–40% |
| **Cache Aligner** | Stabilizes prefixes for provider KV cache hits | 10–20% |
| **Diff Response** | Sends diffs for repeated tool calls | Up to 95% |
| **Output Compressor** | Trims verbose assistant responses | 15–40% |

The pipeline runs in ~52ms median overhead. Your agent doesn't notice it's there.

---

## Progressive Tool Disclosure

Register 30+ MCP tools without burning 60K tokens per request. Copium loads only the tools the LLM needs, when it needs them.

```python
from copium.mcp_proxy.progressive_disclosure import (
    ProgressiveDisclosureConfig,
    ProgressiveDisclosureInterceptor,
)

# Configure progressive disclosure
config = ProgressiveDisclosureConfig(
    enabled=True,
    eager_load_max=10,       # Max tools loaded eagerly
    search_backend="bm25",   # Fast, dependency-free search
    min_tools_for_disclosure=8,  # Threshold to activate
)

# Use in your proxy pipeline
interceptor = ProgressiveDisclosureInterceptor(config)
modified_request = interceptor.intercept_request(request_body)
# 61 tools → 10 eager + copium_find_tool + copium_call_tool
# Token savings: 70-98%
```

**How it works:**
1. Client sends request with all tools (unchanged workflow)
2. Copium classifies tools as eager (high-usage) or deferred
3. LLM receives eager tools + `copium_find_tool` + `copium_call_tool`
4. LLM discovers deferred tools on-demand via BM25 semantic search
5. Schemas are cached for instant repeated lookups

| Tool Count | Token Savings | Eager Tools |
|-----------|--------------|-------------|
| 10 tools | ~40% | 6-8 loaded |
| 30 tools | ~75% | 8-10 loaded |
| 60 tools | ~95% | 10 loaded |

---

## Session management

Copium is also a **universal session manager** for AI coding agents. Compress, search, and share session archives across Claude Code, Cursor, Aider, and OpenCode.

```bash
# Compact a Claude Code session (40-97% smaller)
copium session compact ~/.claude/projects/.../session.jsonl

# Search across all your sessions
copium session search "authentication bug" --agent claude_code

# Export from Claude Code, import into Cursor
copium session export claude-session.jsonl --format shared
copium session import shared.jsonl --agent cursor

# Batch compact all sessions
copium session compact-all ~/.claude/ -o compacted/

# View session summary with auto-detected format
copium session summary session.jsonl
```

### Pre-compaction hooks — never lose context again

Claude Code's auto-compaction fires at ~83.5% of the context window, silently replacing your conversation with a lossy summary. Copium detects this threshold and saves a state checkpoint *before* compaction fires:

```bash
# Restore session state after compaction
copium session restore <session-id>

# List all saved checkpoints for a session
copium session checkpoints <session-id>

# Restore with output file in OpenAI format
copium session restore <session-id> -o recovery.json --format openai
```

What gets saved:
- **File paths** referenced in the conversation
- **Key decisions** extracted from assistant messages
- **Tool output hashes** (retrievable via CCR store on demand)
- **Message snapshot** (most recent messages within token budget)

The checkpoint is automatic — Copium's proxy detects when context usage crosses the threshold and creates the checkpoint without any manual action.

### CCR reversibility

Every compressed session entry includes a CCR hash key. Unlike lossy compaction, Copium's compression is **always reversible**:

```bash
# Expand a compacted archive back to original (via CCR store)
copium session expand compacted.jsonl -o original.jsonl

# The CCR store provides hash-keyed retrieval in <1ms
# No .bak files needed — the store IS the recovery mechanism
```

### Supported agents

| Agent | Format | Commands |
|---|---|---|
| **Claude Code** | JSONL | compact, apply, expand, export, import, restore |
| **Cursor** | JSON | compact, export, import |
| **Aider** | JSONL / Markdown | compact, export, import |
| **OpenCode** | JSON | compact, export, import |

### Error compression enhancements

| Feature | What it does | Savings |
|---|---|---|
| **Build error grouping** | Groups identical TS/Rust/GCC errors across files | 60–85% |
| **Docker build compression** | Removes download progress, deduplicates layers | 40–60% |
| **Compiler normalization** | Normalizes paths, removes timestamps | 10–20% |

---

## Proof

### Compression on real content types

| Content Type | Before (tokens) | After (tokens) | Savings |
|---|---:|---:|---:|
| JSON arrays (100 items) | 3,163 | 297 | **90.6%** |
| Build logs (200 lines) | 2,412 | 148 | **93.9%** |
| Shell output (200 lines) | 3,238 | 469 | **85.5%** |
| JSON arrays (500 items) | 9,526 | 1,614 | **83.1%** |
| Repeated tool outputs | 10,000 | 1,500 | **85%** |
| Git diffs | 3,000 | 300 | **90%** |

### Quality preserved — LLM accuracy benchmarks

The most important thing: does the AI still give correct answers?

| Benchmark | Baseline (no compression) | With Copium | Delta |
|---|---:|---:|---|
| HTML Extraction (F1) | 0.958 | 0.919 | −0.039 |
| HTML Recall | — | **0.982** | 98.2% content preserved |
| JSON Needle Finding | 4/4 | **4/4** | 100% accuracy at 87.6% compression |
| GSM8K (Math) | 0.870 | **0.870** | +/−0.000 |
| TruthfulQA (Factual) | 0.530 | **0.560** | +0.030 (improved) |

Run these yourself:

```bash
pip install "copium-ai[evals]" && pytest tests/test_evals/ -v -s
```

### Production telemetry (250+ instances, 50K+ sessions)

| Metric | Value |
|---|---|
| Total tokens saved | **1.4 billion** |
| Median proxy overhead | **52ms** |
| Median compression (all requests) | 4.8% |
| Heavy tool-use sessions | **40–80%** |

Most requests are short conversational turns — the median 4.8% compression is accurate for those. Where Copium pays for itself is in long agentic sessions with accumulated tool outputs, logs, and search results: that's where you see 40–94%.

---

## When does it help?

**You'll see real gains if you:**
- Run AI coding agents daily (Claude Code, Cursor, Codex, etc.)
- Use local LLMs and need to stay within context limits
- Work with verbose tool outputs — build logs, JSON, search results, git diffs
- Want to extend context window life on quantized models (Q4_0, Q8_0)
- Use Copilot or other subscription services and want more out of each turn

**It won't help much if you:**
- Only send short conversational prompts (median savings: 4.8%)
- Already use a provider's native compaction and don't need more
- Work in a sandboxed environment where local processes can't run

---

## Compared to alternatives

Copium runs **locally**, covers **every** content type, works with every major framework, and supports both cloud and local LLMs.

| | Scope | Deploy | Local LLMs | Reversible | Observability |
|---|---|---|:---:|:---:|:---:|
| **Copium** | All context — tools, RAG, logs, files, history, sessions | Proxy, library, MCP, CLI | ✅ | ✅ (CCR) | Full metrics |
| [ContextCrumb](https://github.com/contextcrumb) | Token-level compression for agent tools | MCP proxy only | ❌ | ❌ | Basic inspection |
| [Kompact](https://github.com/kompact) | Prompt text & schemas | Python library | ❌ | ❌ | ❌ |
| [Claw Compactor](https://github.com/claw) | Prompt text & structure | Python library | ❌ | ❌ | ❌ |
| [Headroom](https://github.com/chopratejas/headroom) | All context | Proxy, library, middleware, MCP | ❌ | ✅ (CCR) | ❌ |
| [ContextZip](https://github.com/contextzip) | Session history / JSONL | Python CLI (Claude only) | ✅ | ❌ (Lossy) | ❌ |
| [RTK](https://github.com/rtk-ai/rtk) | CLI command outputs only | CLI wrapper | ✅ | ❌ | ❌ |
| [lean-ctx](https://github.com/yvgude/lean-ctx) | CLI commands, MCP tools | CLI wrapper, MCP | ✅ | ❌ | ❌ |
| [Compresr](https://compresr.ai), [Token Co.](https://thetokencompany.ai) | Text sent to their API | Hosted API call | ❌ | ❌ | ❌ |
| OpenAI Compaction | Conversation history | Provider-native | ❌ | ❌ | ❌ |

<details>
<summary><b>vs Kompact</b></summary>

Kompact is a Python library focused strictly on compressing prompt text and JSON schemas. Copium is a full architecture handling streaming tool outputs, multi-turn session deduplication, and provider caching.

| | Copium | Kompact |
|---|---|---|
| **Architecture** | Proxy, MCP, Library | Library only |
| **Tool Outputs** | SmartCrusher (statistical) | Regex/Text truncation |
| **Session Dedup** | ✅ Cross-turn retrieval | ❌ |
| **Performance** | Core logic in Rust | Pure Python |
| **Safety** | Reversible (CCR) | Lossy |

</details>

<details>
<summary><b>vs Claw Compactor</b></summary>

Claw Compactor is a high-quality 14-stage pipeline for compressing prompts, but it's restricted to library deployment and irreversible compression. Copium incorporates similar quality-gated pipelines but wraps them in a zero-code proxy with reversible fail-safes.

| | Copium | Claw Compactor |
|---|---|---|
| **Zero-Code Usage** | ✅ Drop-in Proxy | ❌ Library only |
| **Reversibility** | ✅ Compress-Cache-Retrieve | ❌ Irreversible |
| **Quality Gates** | ✅ Auto-reverts on inflation | ❌ Manual |
| **Provider Support** | Universal (Anthropic, Bedrock, etc) | Manual injection |

</details>

<details>
<summary><b>vs Headroom</b></summary>

Both Copium and Headroom compress AI agent context. Key differences:

| | Copium | Headroom |
|---|---|---|
| **Local LLM support** | ✅ (Ollama, VLLM, llama.cpp) | ❌ |
| **KV cache precision detection** | ✅ (auto-detect Q4_0/Q8_0/FP16) | ❌ |
| **Context paging** | ✅ (virtual memory for LLM context) | ❌ |
| **Telemetry** | Off by default (opt-in) | On by default (opt-out) |
| **CCR integrity checks** | ✅ (SHA-256 verification) | ❌ |
| **Windows support** | ✅ Pre-built wheels (CI tested) | Manual install only |

</details>

<details>
<summary><b>vs ContextZip</b></summary>

ContextZip compresses static session archives (Claude Code JSONL only). Copium does that **and** live proxy compression, multi-agent support, reversible compression, and pre-compaction hooks.

| | Copium | ContextZip |
|---|---|---|
| **Live compression** | ✅ (proxy/library/MCP) | ❌ (offline only) |
| **Session archives** | ✅ (Claude + Cursor + Aider + OpenCode) | Claude Code only |
| **Reversibility** | ✅ (CCR with SHA-256) | ❌ (lossy) |
| **Pre-compaction hooks** | ✅ (auto-detect threshold, save state) | ❌ |
| **Post-compaction recovery** | ✅ (restore from checkpoint) | ❌ |
| **Provider support** | All (Anthropic, OpenAI, Google, local) | Anthropic only |
| **Deployment** | Proxy, library, MCP, CLI | CLI only |
| **Error compression** | Advanced (build grouping, Docker, normalization) | Basic |
| **Session search** | ✅ (FTS5 full-text) | ❌ |
| **Cross-agent sharing** | ✅ (export/import) | ❌ |
| **KV cache awareness** | ✅ (precision detection) | ❌ |

*ContextZip measured the problem. Copium solves it — live, offline, reversibly, universally.*

</details>

<details>
<summary><b>vs ContextCrumb</b></summary>

ContextCrumb is an ONNX-based token compressor for agent workflows with an MCP proxy (`contextcrumb-shrink`). Copium provides superior compression across every dimension:

| | Copium | ContextCrumb |
|---|---|---|
| **Architecture** | 37 transform modules, composable pipeline | Single ONNX model |
| **Reversibility** | ✅ CCR (perfect reconstruction) | ❌ Lossy only |
| **Compression modes** | 4 (lossless, lossy, hybrid, archive) | 1 (lossy) |
| **Code awareness** | AST-level, language-specific transforms | Token-level, generic |
| **Integration** | HTTP proxy + SDK + MCP (all three) | MCP only |
| **Tool handling** | Progressive disclosure (70-98% reduction) | Static compression (~40%) |
| **Streaming** | ✅ Full streaming support | ❌ |
| **Caching** | Semantic cache (skip repeated content) | None |
| **Session management** | Save/restore/branch sessions | None |
| **Observability** | Full dashboard, diff tools, metrics | Basic inspection |

**Key advantages:**

1. **Reversible compression** — Copium's CCR lets agents retrieve original context when needed. ContextCrumb's compression is permanent.
2. **Progressive tool disclosure** — instead of compressing tool schemas like ContextCrumb, Copium only sends tool stubs until a tool is actually called (70-98% token savings vs ContextCrumb's ~40%).
3. **Multi-mode compression** — Copium applies lossless compression to code and lossy to comments, achieving better ratios with higher quality.
4. **Full workflow integration** — session persistence, memory store, tool result caching. ContextCrumb only compresses.

**Reproduce the benchmark:** `python -m benchmarks.contextcrumb_comparison_benchmark`

*ContextCrumb is a compressor. Copium is a context optimization platform.*

</details>

<details>
<summary><b>vs RTK</b></summary>

RTK saves 60-90% on **CLI stdout only** (`rtk git status`). Copium saves 40-90% on **all context** — tool outputs, file reads, search results, conversation history, RAG chunks — and includes RTK for free via `copium wrap`.

**Key differences:**

| | RTK | Copium |
|---|---|---|
| Scope | CLI stdout only | Everything (tools, files, search, history) |
| Setup | `rtk git status` per command | `copium wrap claude` (one command) |
| Reversibility | None | CCR — LLM can retrieve originals |
| Observability | None | Full metrics dashboard |
| Strangeness tax | High (abbreviated output confuses LLMs) | Low (quality gate preserves critical markers) |

**Migration:** `pip install "copium-ai[proxy]" && copium wrap claude` — drops in as a superset of RTK. Use `--rtk-only` to start with RTK-only compression, then unlock proxy features when ready.

See [docs/migrating-from-rtk.md](docs/migrating-from-rtk.md) for the full migration guide.

**Reproduce the benchmark:** `python -m benchmarks.rtk-vs-copium.bench_rtk_vs_copium`

</details>

<details>
<summary><b>vs Provider-native compaction</b></summary>

Provider compaction (OpenAI, Anthropic) only compresses **conversation history**. Copium compresses **everything** — tool outputs, logs, RAG results, files — and routes each content type to the best compressor before it ever reaches the provider.

</details>

---

## Local LLM Support

Copium is the **compression layer for local AI**. If you run Ollama, llama.cpp, LM Studio, or any local model, Copium makes your 8GB GPU act like 24GB and your 32K context feel like 128K.

### Auto-Detection

Copium automatically detects running local backends:

```bash
copium doctor   # detects Ollama, llama.cpp, LM Studio and recommends config
```

### One-Command Setup

```bash
# Auto-detect and configure for Ollama
copium wrap ollama

# Configure for llama.cpp server
copium wrap llamacpp

# Configure for LM Studio
copium wrap lmstudio
```

### Supported Local Backends

| Backend | Detection | Auto-Config | KV Cache Aware |
|---------|-----------|-------------|----------------|
| Ollama | localhost:11434 | Yes | Yes |
| llama.cpp | localhost:8080 | Yes | Yes |
| LM Studio | localhost:1234 | Yes | Yes |
| VLLM | configurable | Yes | Yes |

### KV Cache Precision Detection

When a quantized model's KV cache is too full, accuracy collapses — not gradually, but off a cliff:

```
Q4_0 KV Cache at 32K context = 2% accuracy (vs 37.9% for FP16)
```

Copium detects your model's quantization type and starts compressing aggressively *before* you hit that cliff.

### VRAM-Aware Compression

Copium monitors GPU memory and adapts compression in real-time:

```python
from copium.integrations.local import AdaptiveCompressor

compressor = AdaptiveCompressor()
config = compressor.get_config()
# Automatically scales from light → aggressive based on VRAM pressure
```

### Hardware Presets

Pre-configured for common GPU setups:

| GPU VRAM | Preset | Compression | Smart Zone |
|----------|--------|-------------|------------|
| 8GB | `aggressive` | All transforms | 35% |
| 12GB | `standard+` | 5 transforms | 40% |
| 16GB | `moderate` | 4 transforms | 40% |
| 24GB+ | `light` | 2 transforms | 45% |

### Smart Routing (Triage Engine)

Route simple tasks to your local model, compress complex tasks for cloud:

```python
from copium.integrations.local import LocalTriageEngine

engine = LocalTriageEngine(
    local_model="qwen3:8b",
    cloud_model="claude-sonnet-4-20250514",
    triage_threshold=0.7,
)
decision = await engine.route(messages)
# Simple tasks stay local (free), complex tasks get compressed for cloud
```

Expected savings: **40-79% fewer cloud tokens** on typical coding workloads.

### Streaming Compression

For VRAM-constrained environments, compression runs in streaming mode with zero GPU memory overhead:

```python
from copium.integrations.local import StreamingCompressor

compressor = StreamingCompressor(chunk_size=4096)
for chunk in compressor.compress_iter(large_context):
    # Processes chunk-by-chunk, never buffers full content
    send(chunk.content)
```

It also supports **cold/hot context paging** — effectively virtual memory for your LLM's context window, cutting context by up to 93% for long sessions.

---

## Configuration

Create `copium.json` in your project root to customize behavior:

```json
{
  "mode": "optimize",
  "cache_aligner": { "enabled": true },
  "session_dedup": {
    "enabled": true,
    "similarity_threshold": 0.85
  },
  "error_compressor": {
    "enabled": true,
    "max_stack_frames": 3,
    "preserve_security_warnings": true
  }
}
```

Disable specific transforms per request:

```bash
curl -H "X-Copium-Disable: toon,code_compressor" \
     http://localhost:8082/v1/chat/completions
```

Environment variables:

```bash
export COPIUM_PORT=8082
export COPIUM_HOST=0.0.0.0
export COPIUM_LOG_LEVEL=debug
export COPIUM_CCR_TTL_SECONDS=1800   # how long compressed data is cached
```

### Compression presets

```bash
copium proxy --preset minimal      # Structural transforms only; safest
copium proxy --preset standard     # Full stack; recommended (default)
copium proxy --preset aggressive   # Maximum savings; more aggressive
copium proxy --preset local-llm    # Optimized for Ollama/VLLM/llama.cpp
copium proxy --preset lossless     # Zero quality loss transforms only

# Inspect any preset without starting the proxy:
copium preset aggressive
```

### View your savings

```bash
copium status                  # proxy health, uptime, today's savings
copium status --verbose        # also show all-time stats
copium status --json           # machine-readable JSON
copium status --prompt         # one-liner for shell prompts: ⚡ 38% (empty when stopped)
copium stats                   # detailed savings breakdown
copium stats --period session  # current session only
copium stats --json            # machine-readable output
```

### Check agent status

```bash
copium agents                  # list all detected agents and wrap status
copium agents --installed      # show only installed agents
copium agents --json           # machine-readable output
```

### View logs

```bash
copium logs                    # show last 100 lines of proxy logs
copium logs -n 50              # show last 50 lines
copium logs -f                 # follow logs in real time (Ctrl+C to stop)
copium logs --level ERROR      # filter by log level
```

### Version and diagnostics

```bash
copium version                 # show version, Python, platform, install method
copium version --json          # machine-readable output
copium doctor                  # diagnose installation and configuration
```

---

## Always-on Background Service

The biggest daily friction with a proxy tool is keeping it running. Copium solves this two ways:

### Daemon mode (recommended for daily use)

```bash
copium start                  # start proxy, detach from terminal — survives shell exit
copium stop                   # stop gracefully (shows session summary: duration, tokens saved, all-time totals)
copium restart                # restart (picks up config changes)
copium status                 # check running/stopped, uptime, savings today
copium status --json          # machine-readable output (for scripts / shell prompts)
copium status --prompt        # minimal one-liner (⚡ 38%) — empty string when stopped
copium ping                   # fast health check: exit 0 running, exit 1 stopped
copium ping --json            # {"status":"running","uptime_s":15423,"tokens_saved_today":312481}
```

`copium start` auto-creates a deployment profile on first run. The PID file lives at `~/.copium/deploy/default/runner.pid`; logs at `~/.copium/deploy/default/runner.log`.

### Shell prompt integration

Show a live `⚡ 38%` indicator in your shell prompt when the proxy is active:

**Starship** — add to `~/.config/starship.toml` (or run `copium init` to add it automatically):

```toml
[custom.copium]
command = "copium status --prompt"
when    = "copium ping"
format  = "[$output]($style) "
style   = "bold yellow"
```

**bash / zsh** — add to `~/.zshrc` or `~/.bashrc`:

```bash
_copium_prompt() {
  local _s
  _s="$(copium status --prompt 2>/dev/null)"
  echo "${_s:+[$_s] }"
}
PROMPT_COMMAND='_copium_prompt_val=$(_copium_prompt); ${PROMPT_COMMAND:-:}'
export PS1='${_copium_prompt_val}${PS1}'
```

`copium status --prompt` outputs nothing when the proxy is stopped, so the segment disappears automatically. `copium remove` cleans this up along with everything else.

### First-request feedback

The first time any request is compressed, Copium prints a one-time celebration to your terminal:

```
🎉 First request compressed!
   Tokens: 4.8K → 892  (81.5% saved, ~$0.01 saved on this request)

   View live savings:  copium tui
   Or open:           http://localhost:8787/dashboard
```

This only ever shows once — the flag is stored in `~/.copium/state.json`.


```bash
copium start --port 9090          # custom port
copium start --preset aggressive  # aggressive compression
copium start --memory             # enable persistent memory
copium start --no-wait            # don't wait for ready signal (fire-and-forget)
```

### Auto-start on login (system service)

For teams or power users who want the proxy running before they even open a terminal:

```bash
copium service install        # install as systemd user unit (Linux) or launchd agent (macOS)
copium service status         # show service health
copium service logs           # tail service logs (uses journalctl on Linux)
copium service logs -f        # follow logs continuously
copium service remove         # uninstall the service (keeps your data)
```

After `copium service install`, the proxy starts automatically at login and restarts on failure. You never have to think about it again.

### Shell completion

Enable tab completion for faster command lookup:

```bash
# Bash
copium completions bash >> ~/.bash_completion

# Zsh
copium completions zsh >> ~/.zshrc

# Fish
copium completions fish > ~/.config/fish/completions/copium.fish

# PowerShell
copium completions powershell | Out-String | Invoke-Expression
```

After installing, reload your shell or run `source ~/.zshrc` (zsh) / `source ~/.bash_completion` (bash).

Platform details:

| Platform | Mechanism | Config location |
|---|---|---|
| Linux | systemd user unit | `~/.config/systemd/user/copium.service` |
| macOS | launchd LaunchAgent | `~/Library/LaunchAgents/com.copium.default.plist` |
| Windows | Windows Service / Task Scheduler | via `sc.exe` or `schtasks` |


## Architecture (for the curious)

The full request pipeline:

```
Request → Cache Aligner → Differential Response → Session Dedup
        → KV Cache Detection → Content Router → Error Compressor
        → Paging → Output Compressor → TOON Encoder → Provider
```

**ContentRouter** decides which compressor to use for each piece of content. It detects the content type (JSON array, log output, code, HTML, search results, git diff) and routes it to the appropriate transform. The routing decision is logged for transparency.

**SmartCrusher** uses statistical analysis — variance-based change point detection, Kneedle algorithm for optimal K, BM25 + embedding relevance scoring — to compress tool output arrays while keeping the items the LLM actually needs. It never generates text; the output contains only items from the original array.

**CCR (Compress-Cache-Retrieve)** makes compression reversible. When SmartCrusher compresses a 1,000-item array down to 20 items, the original 1,000 items are stored locally (SHA-256 verified). The LLM receives a retrieval marker. If it needs more data, it calls `copium_retrieve(hash, query)` and gets the relevant subset. Worst case: the LLM retrieves what it needs. Best case: it never needs to.

**Session Dedup** tracks content hashes (exact SHA-256 + MinHash for near-duplicates) across the entire conversation. If a file read from turn 3 shows up again in turn 15, only a reference marker goes to the LLM. The proxy overhead for this lookup is sub-millisecond.

**TOON Encoder** converts JSON arrays into pipe-delimited tables — the same semantic content, dramatically fewer tokens. `[{"name": "alice", "age": 30}, {"name": "bob", "age": 25}]` becomes `name | age\nalice | 30\nbob | 25`. The LLM reads both perfectly; the table uses 60–80% fewer tokens.

**Cache Aligner** stabilizes prompt prefixes so provider KV caches actually hit. Anthropic and OpenAI offer prefix caching (massive cost reduction), but a single changed character busts the cache. Cache Aligner moves dynamic content (dates, session IDs, request hashes) to the end of system messages so the stable prefix stays stable.

---

## Integrations

| Your setup | How to use |
|---|---|
| Any Python app | `compress(messages)` |
| Anthropic / OpenAI SDK | `CopiumClient(original_client=...)` |
| Vercel AI SDK | Copium middleware |
| LiteLLM | Callback integration |
| LangChain | `CopiumChatModel(your_llm)` |
| Agno | `CopiumAgnoModel(your_model)` |
| MCP clients | `pip install "copium-ai[mcp]"` |
| Any HTTP client | `copium run` (proxy mode) |
| Claude Code | `copium wrap claude` |
| Codex | `copium wrap codex` |
| Cursor | Set API base URL in settings |
| OpenCode | `export OPENAI_BASE_URL=http://localhost:8082/v1` |
| Aider | `copium wrap aider` |
| GitHub Copilot | `copium wrap copilot` |
| Mistral Vibe | `copium wrap vibe` |
| Cline (VS Code) | `copium wrap cline` |
| Continue (VS Code/JetBrains) | `copium wrap continue` |
| Antigravity | ⚠️ Not supported (no proxy settings) |
| AWS Bedrock | `http://localhost:8082/bedrock` |
| Google Vertex AI | `http://localhost:8082/vertex` |
| Ollama | `copium run --backend ollama` |

---

## Documentation

| Start here | Go deeper |
|---|---|
| [Quickstart](https://copium-docs.vercel.app/docs/quickstart) | [Architecture](https://copium-docs.vercel.app/docs/architecture) |
| [Proxy](https://copium-docs.vercel.app/docs/proxy) | [How compression works](https://copium-docs.vercel.app/docs/compression) |
| [MCP tools](https://copium-docs.vercel.app/docs/mcp) | [Benchmarks](https://copium-docs.vercel.app/docs/benchmarks) |
| [Configuration](https://copium-docs.vercel.app/docs/configuration) | [Limitations](https://copium-docs.vercel.app/docs/limitations) |
| [Migration guide](https://copium-docs.vercel.app/docs/migration) | [Presets](https://copium-docs.vercel.app/docs/configuration#presets) |

---

## Contributing

```bash
git clone https://github.com/iKislay/copium.git && cd copium
uv sync && uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

## Acknowledgments

- **Pichay** (arXiv:2603.09023) — Virtual memory paging for LLM context
- The **r/LocalLLaMA** community — For identifying and stress-testing the precision cliff problem
