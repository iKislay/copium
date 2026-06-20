# Configuration

Copium can be configured via the SDK, proxy command line, or per-request overrides.

## SDK Configuration

```python
from copium import CopiumClient, OpenAIProvider
from openai import OpenAI

client = CopiumClient(
    original_client=OpenAI(),
    provider=OpenAIProvider(),

    # Mode: "audit" (observe only) or "optimize" (apply transforms)
    default_mode="optimize",

    # Enable provider-specific cache optimization
    enable_cache_optimizer=True,

    # Enable query-level semantic caching
    enable_semantic_cache=False,

    # Override default context limits per model
    model_context_limits={
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
    },

    # Database location (defaults to temp directory)
    # store_url="sqlite:////absolute/path/to/copium.db",
)
```

## Proxy Configuration

### Command Line Options

```bash
copium proxy \
  --port 8787 \              # Port to listen on
  --host 0.0.0.0 \           # Host to bind to
  --budget 10.00 \           # Daily budget limit in USD
  --log-file copium.jsonl  # Log file path
```

### Feature Flags

```bash
# Disable optimization (passthrough mode)
copium proxy --no-optimize

# Disable semantic caching
copium proxy --no-cache

# Disable CCR response handling
copium proxy --no-ccr-responses

# Disable proactive expansion
copium proxy --no-ccr-expansion

# (The earlier --llmlingua flag was retired in 0.9.x and replaced by
# Kompress (ModernBERT). See `wiki/transforms.md` for the current
# opt-in path via the `[ml]` extra.)
```

### All Options

```bash
copium proxy --help
```

### Kompress backend selection

Kompress (the model-based compressor) can run on two engines:

- **ONNX Runtime** — lightweight, CPU-first. Installed with
  `pip install copium-ai[proxy]`. Optionally uses the CoreML execution
  provider on macOS.
- **PyTorch** — heavier, supports CUDA and Apple-Silicon MPS
  acceleration. Installed with `pip install copium-ai[ml]`. With
  `device=auto` it selects `cuda`, then `mps`, then `cpu`.

Select the backend via the `COPIUM_KOMPRESS_BACKEND` environment
variable:

| Value               | Behavior                                                               |
|---------------------|------------------------------------------------------------------------|
| `auto`              | Default. ONNX CPU first (stable, lightweight), PyTorch as fallback.    |
| `onnx` / `onnx_cpu` | Force ONNX Runtime on CPU.                                             |
| `onnx_coreml`       | Force ONNX Runtime with the CoreML provider (CPU fallback).            |
| `pytorch`           | Force PyTorch with automatic device selection (CUDA → MPS → CPU).      |
| `pytorch_mps`       | Force PyTorch on Apple-Silicon MPS; falls back to ONNX CPU on failure. |

Values are case-insensitive and hyphens are accepted (`onnx-cpu` ==
`onnx_cpu`). Shorthand aliases: `cpu` → `onnx_cpu`, `coreml` →
`onnx_coreml`, `mps` / `torch_mps` → `pytorch_mps`, `torch` →
`pytorch`. Unrecognized values log a warning and fall back to `auto`.

Example — opt in to MPS on an Apple-Silicon machine:

```bash
export COPIUM_KOMPRESS_BACKEND=mps
copium proxy ...
```

The default deliberately stays on ONNX CPU so existing installs keep
their compression quality and performance characteristics; accelerator
backends are opt-in.

## Per-Request Overrides

Override configuration for specific requests:

```python
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[...],

    # Override mode for this request
    copium_mode="audit",

    # Reserve more tokens for output
    copium_output_buffer_tokens=8000,

    # Keep last N turns (don't compress)
    copium_keep_turns=5,

    # Skip compression for specific tools
    copium_tool_profiles={
        "important_tool": {"skip_compression": True}
    }
)
```

## Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| `audit` | Observes and logs, no modifications | Production monitoring, baseline measurement |
| `optimize` | Applies safe, deterministic transforms | Production optimization |
| `simulate` | Returns plan without API call | Testing, cost estimation |

### Simulate Mode

Preview what would happen without making an API call:

```python
plan = client.chat.completions.simulate(
    model="gpt-4o",
    messages=large_conversation,
)

print(f"Would save {plan.tokens_saved} tokens")
print(f"Transforms: {plan.transforms}")
print(f"Estimated savings: {plan.estimated_savings}")
```

## SmartCrusher Configuration

Fine-tune JSON compression behavior:

```python
from copium.transforms import SmartCrusherConfig

config = SmartCrusherConfig(
    # Maximum items to keep after compression
    max_items_after_crush=15,

    # Minimum tokens before applying compression
    min_tokens_to_crush=200,

    # Relevance scoring tier: "bm25" (fast) or "embedding" (accurate)
    relevance_tier="bm25",

    # Always keep items with these field values
    preserve_fields=["error", "warning", "failure"],
)
```

## Cache Aligner Configuration

Control prefix stabilization:

```python
from copium.transforms import CacheAlignerConfig

config = CacheAlignerConfig(
    # Enable/disable cache alignment
    enabled=True,

    # Patterns to extract from system prompt
    dynamic_patterns=[
        r"Today is \w+ \d+, \d{4}",
        r"Current time: .*",
    ],
)
```

## Rolling Window Configuration

Control context window management:

```python
from copium.transforms import RollingWindowConfig

config = RollingWindowConfig(
    # Minimum turns to always keep
    min_keep_turns=3,

    # Reserve tokens for output
    output_buffer_tokens=4000,

    # Drop oldest tool outputs first
    prefer_drop_tool_outputs=True,
)
```

## Intelligent Context Manager Configuration

For semantic-aware context management with importance scoring:

```python
from copium.config import IntelligentContextConfig, ScoringWeights

# Customize scoring weights (must sum to 1.0, or will be normalized)
weights = ScoringWeights(
    recency=0.20,              # Newer messages score higher
    semantic_similarity=0.20,  # Similarity to recent context
    toin_importance=0.25,      # TOIN-learned retrieval patterns
    error_indicator=0.15,      # TOIN-learned error field types
    forward_reference=0.15,    # Messages referenced by later messages
    token_density=0.05,        # Information density
)

config = IntelligentContextConfig(
    # Enable/disable the manager
    enabled=True,

    # Protection settings
    keep_system=True,           # Never drop system messages
    keep_last_turns=2,          # Protect last N user turns

    # Token budget
    output_buffer_tokens=4000,  # Reserve for model output

    # Scoring settings
    use_importance_scoring=True,    # Use semantic scoring (vs position-only)
    scoring_weights=weights,        # Custom weights
    toin_integration=True,          # Use TOIN patterns if available
    recency_decay_rate=0.1,         # Exponential decay lambda

    # Strategy thresholds
    compress_threshold=0.1,     # Try compression first if <10% over budget
)
```

### CCR Integration

When IntelligentContext drops messages, they're stored in CCR for potential retrieval:

```python
from copium.telemetry import get_toin

# Pass TOIN for bidirectional integration
toin = get_toin()
manager = IntelligentContextManager(config=config, toin=toin)

# Dropped messages are:
# 1. Stored in CCR (so LLM can retrieve if needed)
# 2. Recorded to TOIN (so it learns which patterns matter)
# 3. Marked with CCR reference in the inserted message
```

The marker inserted when messages are dropped includes the CCR reference:
```
[Earlier context compressed: 14 message(s) dropped by importance scoring.
Full content available via ccr_retrieve tool with reference 'abc123def456'.]
```

### Scoring Weights

The `ScoringWeights` class controls how messages are scored:

| Weight | Default | Description |
|--------|---------|-------------|
| `recency` | 0.20 | Exponential decay from conversation end |
| `semantic_similarity` | 0.20 | Embedding cosine similarity to recent context |
| `toin_importance` | 0.25 | TOIN retrieval_rate (high retrieval = important) |
| `error_indicator` | 0.15 | TOIN field_semantics error detection |
| `forward_reference` | 0.15 | Count of later messages referencing this one |
| `token_density` | 0.05 | Unique tokens / total tokens |

Weights are automatically normalized to sum to 1.0:

```python
weights = ScoringWeights(recency=1.0, toin_importance=1.0)
normalized = weights.normalized()
# recency=0.5, toin_importance=0.5, others=0.0
```

## Environment Variables

Some settings can be configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `COPIUM_MODEL_LIMITS` | Custom model config (JSON string or file path) | - |
| `COPIUM_CONFIG_DIR` | Canonical config (read-mostly) root. Derives `models.json` and per-plugin config paths when set. | `~/.copium/config` |
| `COPIUM_WORKSPACE_DIR` | Canonical workspace (read-write state) root. Derives savings ledger, memory DB, logs, TOIN, subscription state, and more when set. | `~/.copium` |
| `COPIUM_SAVINGS_PATH` | Full path to the proxy savings JSON ledger. Always wins when set. | derived from `${COPIUM_WORKSPACE_DIR}` |
| `COPIUM_TOIN_PATH` | Full path to the TOIN telemetry JSON file. Always wins when set. | derived from `${COPIUM_WORKSPACE_DIR}` |
| `COPIUM_SUBSCRIPTION_STATE_PATH` | Full path to the subscription tracker state. Always wins when set. | derived from `${COPIUM_WORKSPACE_DIR}` |
| `COPIUM_EMBEDDER_RUNTIME` | Set to `pytorch_mps` to run the memory embedder via the torch sentence-transformers backend on the Apple GPU (MPS). Only engages when Apple MPS is actually available; otherwise it logs a warning and uses the existing default embedder selection path. `pytorch_mps` is the only accepted value. Requires the `[pytorch-mps]` extra. See [Memory](memory.md#embedding-runtime--gpu-offload-apple-silicon). | default embedder selection |
| `COPIUM_BETA_HEADER_STICKY` | Controls per-session `anthropic-beta` / `OpenAI-Beta` re-echo. `enabled` (default): the proxy unions beta tokens across turns within a session — if the client sends a token in turn N and omits it in turn N+1, the proxy re-injects it to preserve prefix-cache stability. `disabled`: the client's value is forwarded verbatim with no accumulation. Any other value raises at request time. See [Session Beta Header Tracking](#session-beta-header-tracking). | `enabled` |
| `COPIUM_BETA_TRACKER_MAX_SESSIONS` | LRU capacity of the in-memory session beta tracker. Once full, the oldest session entry is evicted. | `1000` |

## Session Beta Header Tracking

When running as a proxy, Copium maintains a per-session union of `anthropic-beta` (and `OpenAI-Beta`) tokens via `SessionBetaTracker`. The session key is derived from the `x-copium-session-id` header if present, otherwise from `md5(model + system_prompt[:500])[:16]` — stable across turns of the same conversation.

**Why:** clients such as Claude Code and Codex CLI may drop a beta token between consecutive turns. Because `anthropic-beta` is part of the request bytes that determine the upstream prefix-cache key, a dropped token would bust the cache mid-conversation. The tracker re-injects any token seen earlier in the session so the cache key stays stable.

**Trade-off:** once the proxy has seen a beta token in a session it will continue re-sending it for the rest of that session, even if the client stops including it. Stopping the token on the client side alone is not sufficient — the proxy re-injects it. Set `COPIUM_BETA_HEADER_STICKY=disabled` to pass the client's `anthropic-beta` value verbatim and bypass this accumulation.

```bash
# Disable sticky beta re-echo
export COPIUM_BETA_HEADER_STICKY=disabled
copium proxy ...
```

Note: disabling sticky mode may reduce prefix-cache hit rates for clients that legitimately drop-and-re-add beta tokens across turns.

## Filesystem Contract

Copium resolves every on-disk resource through a two-root model:

- `COPIUM_CONFIG_DIR` (default `~/.copium/config`) — read-mostly
  configuration
- `COPIUM_WORKSPACE_DIR` (default `~/.copium`) — read-write state

Precedence for each resource is: explicit argument > per-resource env
var > derived from canonical root > default. Every legacy env var
continues to work unchanged.

See **[Filesystem Contract](filesystem-contract.md)** for the full
bucket table, plugin-author guidance, and the Docker naming overlap
note (`COPIUM_WORKSPACE` is *not* the same as `COPIUM_WORKSPACE_DIR`).

---

## Custom Model Configuration

Configure context limits and pricing for new or custom models. Useful when:
- A new model is released before Copium is updated
- You're using fine-tuned or custom models
- You want to override built-in limits

### Configuration Methods

Settings are resolved in this order (later overrides earlier):
1. Built-in defaults
2. `${COPIUM_CONFIG_DIR}/models.json` (defaults to
   `~/.copium/config/models.json`); falls back to the legacy location
   `~/.copium/models.json` when the canonical file is absent
3. `COPIUM_MODEL_LIMITS` environment variable
4. SDK constructor arguments

### Config File Format

Create `~/.copium/models.json`:

```json
{
  "anthropic": {
    "context_limits": {
      "claude-4-opus-20250301": 200000,
      "claude-custom-finetune": 128000
    },
    "pricing": {
      "claude-4-opus-20250301": {
        "input": 15.00,
        "output": 75.00,
        "cached_input": 1.50
      }
    }
  },
  "openai": {
    "context_limits": {
      "gpt-5": 256000,
      "ft:gpt-4o:my-org": 128000
    },
    "pricing": {
      "gpt-5": [5.00, 15.00]
    }
  }
}
```

### Environment Variable

Set `COPIUM_MODEL_LIMITS` as a JSON string or file path:

```bash
# JSON string
export COPIUM_MODEL_LIMITS='{"anthropic":{"context_limits":{"claude-new":200000}}}'

# File path
export COPIUM_MODEL_LIMITS=/path/to/models.json
```

### Pattern-Based Inference

Unknown models are automatically inferred from naming patterns:

| Pattern | Inferred Settings |
|---------|-------------------|
| `*opus*` | 200K context, Opus-tier pricing |
| `*sonnet*` | 200K context, Sonnet-tier pricing |
| `*haiku*` | 200K context, Haiku-tier pricing |
| `gpt-4o*` | 128K context, GPT-4o pricing |
| `o1*`, `o3*` | 200K context, reasoning model pricing |

This means new models like `claude-4-sonnet-20251201` will work automatically with Sonnet-tier defaults.

### SDK Override

Override in code for specific models:

```python
from copium import CopiumClient, AnthropicProvider

client = CopiumClient(
    original_client=Anthropic(),
    provider=AnthropicProvider(
        context_limits={
            "claude-new-model": 300000,
        }
    ),
)
```

## Provider-Specific Settings

### OpenAI

```python
from copium import OpenAIProvider

provider = OpenAIProvider(
    # Enable automatic prefix caching
    enable_prefix_caching=True,
)
```

### Anthropic

```python
from copium import AnthropicProvider

provider = AnthropicProvider(
    # Enable cache_control blocks
    enable_cache_control=True,
)
```

### Google

```python
from copium import GoogleProvider

provider = GoogleProvider(
    # Enable context caching
    enable_context_caching=True,
)
```

## Configuration Precedence

Settings are applied in this order (later overrides earlier):

1. Default values
2. Environment variables
3. SDK constructor arguments
4. Per-request overrides

## Validation

Validate your configuration:

```python
result = client.validate_setup()

if not result["valid"]:
    print("Configuration issues:")
    for issue in result["issues"]:
        print(f"  - {issue}")
```

---

## TypeScript SDK Configuration

The TypeScript SDK is configured via environment variables or constructor options.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `COPIUM_BASE_URL` | Base URL of the Copium proxy or cloud API | `http://localhost:8787` |
| `COPIUM_API_KEY` | API key for Copium Cloud authentication | - |

### Usage

```bash
export COPIUM_BASE_URL=http://localhost:8787
export COPIUM_API_KEY=your-api-key
```

```typescript
import { CopiumClient } from 'copium-ai';

// Reads from COPIUM_BASE_URL and COPIUM_API_KEY automatically
const client = new CopiumClient();

// Or configure explicitly
const client = new CopiumClient({
  baseUrl: 'http://localhost:8787',
  apiKey: 'your-api-key',
});
```

See the [TypeScript SDK Guide](typescript-sdk.md) for full configuration options.
