# Preventing Pre-Compaction Data Loss

Auto-compaction in agentic coding tools (Claude Code, Cursor, Codex) silently destroys critical context — debugging chains, architectural decisions, file relationships, and user intent. Copium solves this with native state preservation via the CCR architecture and purpose-built compaction hooks.

## The Problem

When a conversation approaches the context window limit (~83.5% for Claude Code), auto-compaction fires silently:

1. Tool outputs are cleared (60-80% of context)
2. Conversation is summarized into a 5-10K token summary
3. Detailed reasoning chains, file relationships, and decisions are lost

This is a 10-20x compression ratio — far too aggressive for meaningful preservation.

## Copium's Solution

### Strategy 1: CCR-First (Zero Configuration)

Start Copium proxy and everything is handled automatically:

```bash
copium proxy --port 8787
ANTHROPIC_BASE_URL=http://localhost:8787 claude
```

What happens:
- Tool outputs are compressed with originals cached in CCR
- User messages are preserved verbatim (never compressed)
- CCR markers tell the LLM what data is available for retrieval
- Context Tracker proactively expands relevant compressed content

### Strategy 2: Input-Priority Compression

Preserve user messages (high entropy, irreplaceable) while compressing tool outputs more aggressively:

```python
from copium.hooks import InputPriorityHooks

hooks = InputPriorityHooks(
    user_bias=0.3,      # Keep user messages at 30% compression
    assistant_bias=1.0,  # Normal compression for assistant
    tool_bias=1.5,       # Aggressive compression for tool outputs
    use_entropy_scoring=True,  # Further adjust by information density
)

# Use with proxy config
copium proxy --port 8787 --hooks input-priority
```

The entropy scorer further adjusts biases based on actual information density — messages with unique, irreplaceable content get preserved more.

### Strategy 3: Incremental Checkpointing

Instead of one catastrophic compaction, save state gradually every N tool calls:

```python
from copium.hooks import IncrementalCheckpointHooks, CheckpointStoreConfig

config = CheckpointStoreConfig(
    checkpoint_interval=10,        # Save every 10 tool calls
    context_threshold_60=0.60,     # Alert at 60% usage
    context_threshold_70=0.70,     # Emergency checkpoint at 70%
    max_checkpoints=20,
)

hooks = IncrementalCheckpointHooks(config=config, session_id="my-session")
```

Checkpoints capture:
- Architectural decisions and trade-offs
- Active file paths and relationships
- Current task state
- Tool call context

### Strategy 4: Claude Code Hook Integration

If you use Claude Code's native hook system, Copium integrates directly:

```bash
# Auto-configure Claude Code hooks
python -m copium.hooks.claude_code init
```

This adds to your `.claude/settings.json`:

```json
{
  "hooks": {
    "PreCompact": [{
      "command": "python -m copium.hooks.claude_code capture",
      "description": "Copium: Save session state before compaction"
    }],
    "PostCompact": [{
      "command": "python -m copium.hooks.claude_code recover",
      "description": "Copium: Restore critical context after compaction"
    }]
  }
}
```

Or use the Python API:

```python
from copium.hooks.claude_code import write_hook_settings, ClaudeCodeHookConfig

config = ClaudeCodeHookConfig(
    capture_file_paths=True,
    capture_decisions=True,
    capture_tool_outputs=True,
    inject_file_paths=True,
    inject_decisions=True,
    inject_ccr_refs=True,
)

write_hook_settings(config)
```

## How It Works

### Pre-Compaction Detection

Copium's `CompactionDetector` monitors context usage and fires events when compaction is imminent:

```
Context Window: [████████████████████░░░░] 83.5% — COMPACTION IMMINENT
                                         ↑
                               Copium fires PreCompact hooks
```

### PreCompact Hook Data

When compaction is detected, hooks receive full context:

```python
from copium.hooks import PreCompactHookData

# Available to your hooks:
data = PreCompactHookData(
    context_tokens_before=180_000,
    context_tokens_after_estimate=60_000,
    messages_count=142,
    tool_calls_count=87,
    compaction_reason="context_limit",
    messages=[...],  # Full message history
    compressed_content={...},  # Hash → content preview
)
```

### Post-Compaction Recovery

After compaction, Copium restores critical context:

```python
from copium.hooks import PostCompactHookData

data = PostCompactHookData(
    context_tokens_after=50_000,
    messages_kept=[...],
    messages_compressed=["hash1", "hash2"],
    ccr_references=["ccr_ref_1", "ccr_ref_2"],
)
# CCR references remain available for on-demand retrieval
```

## Entropy-Based Message Scoring

The `MessageEntropyScorer` analyzes each message's information density:

```python
from copium.hooks import MessageEntropyScorer

scorer = MessageEntropyScorer()
scores = scorer.score_messages(messages)

for score in scores:
    print(f"Message {score.index} ({score.role}):")
    print(f"  Entropy: {score.entropy:.3f}")
    print(f"  Uniqueness: {score.uniqueness:.3f}")
    print(f"  Compressibility: {score.compressibility:.3f}")
    print(f"  Preservation priority: {score.preservation_priority:.3f}")
    print(f"  Compression bias: {score.compression_bias:.3f}")
```

Scoring signals:
- **Entropy**: Shannon entropy of character n-grams (information density)
- **Uniqueness**: Jaccard distance to other messages (how unique is this content?)
- **Compressibility**: Role-based priors + structural analysis
- **Preservation priority**: Combined score determining compression order

## Comparison with Workarounds

| Approach | Effort | Reliability | Coverage |
|----------|--------|-------------|----------|
| Manual `/compact` | High (guessing) | Low | Single tool |
| PreCompact SQLite dump | Medium (build + maintain) | Medium | Claude Code only |
| Relay baton system | High (production infra) | High | Custom |
| CLAUDE.md manual updates | High (discipline) | Low | All tools |
| **Copium CCR** | **Zero** | **High** | **All tools** |
| **Copium hooks** | **Low** (one-time config) | **High** | **All tools** |

## Multi-Agent Support

Copium's compaction prevention works across all major agents:

```bash
# Claude Code
ANTHROPIC_BASE_URL=http://localhost:8787 claude

# Cursor
OPENAI_BASE_URL=http://localhost:8787/v1 cursor

# Codex CLI
copium wrap codex -- --model claude-sonnet-4-20250514

# OpenCode
copium wrap opencode
```

## Further Reading

- [CCR Architecture](ccr.md) — How reversible compression works
- [Compression Guide](compression.md) — Universal compression details
- [Proxy Guide](proxy.md) — Setting up the Copium proxy
- [Integration Guide](integration-guide.md) — Agent-specific setup
