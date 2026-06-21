# Copium

**The context compression layer for LLM applications**

> 50-90% fewer tokens. Zero quality loss. Drop-in proxy for Claude, GPT, Gemini, and local LLMs.

[![PyPI](https://img.shields.io/pypi/v/copium-ai.svg)](https://pypi.org/project/copium-ai/)
[![Python](https://img.shields.io/badge/python-3.10+-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()
[![Docs](https://img.shields.io/badge/docs-online-blue.svg)](https://copium-docs.vercel.app/docs)

<p>
  <a href="https://copium-docs.vercel.app/docs">Docs</a> &middot;
  <a href="#get-started-60-seconds">Install</a> &middot;
  <a href="#proof">Proof</a> &middot;
  <a href="#compared-to">Alternatives</a> &middot;
  <a href="https://github.com/iKislay/copium">GitHub</a>
</p>

---

Copium compresses everything your AI agent sends to an LLM -- tool outputs, logs, RAG chunks, files, and conversation history -- before it reaches the provider. Same answers, fraction of the tokens.

## What it does

- **Proxy** -- `copium run`, zero code changes, works with any language or framework
- **Library** -- `from copium import compress` inline in Python apps
- **MCP server** -- `copium_compress`, `copium_retrieve`, `copium_stats` for any MCP client
- **Local LLM intelligence** -- auto-detects KV cache precision, compresses before the precision cliff
- **Cross-agent memory** -- shared context across Claude, Cursor, Codex, and more

## How it works (30 seconds)

```
 Your agent / app
   (Claude Code, Cursor, Aider, LangChain, your own code...)
        |   prompts, tool outputs, logs, RAG results, files
        v
    +----------------------------------------------------+
    |  Copium   (runs locally -- your data stays here)   |
    |  -------------------------------------------------  |
    |  ContentRouter  ->  SmartCrusher  |  Kompress       |
    |                   Session Dedup   |  Error Cards    |
    |                   Cache Aligner   |  TOON Encoder   |
    +----------------------------------------------------+
        |   compressed prompt
        v
 LLM provider  (Anthropic, OpenAI, Ollama, VLLM, ...)
```

- **ContentRouter** -- detects content type, selects the best compressor
- **SmartCrusher** -- compresses JSON arrays, diffs, repeated tool outputs
- **Session Dedup** -- eliminates re-sent file content across conversation turns
- **Cache Aligner** -- stabilizes prefixes so provider KV caches actually hit
- **Kompress** -- ML-based text compression (ONNX, runs locally)

## Get started (60 seconds)

```bash
# 1 -- Install
pip install "copium-ai[proxy]"       # Python with proxy support
# or
uv tool install "copium-ai[proxy]"

# 2 -- Start the proxy
copium run                           # default: http://localhost:8082

# 3 -- Point your agent at it
export ANTHROPIC_BASE_URL=http://localhost:8082    # Claude Code
export OPENAI_API_BASE=http://localhost:8082/v1    # Cursor / Aider

# 4 -- See the savings
copium dashboard
```

That's it. Copium automatically compresses every request.

### As a library

```python
from copium import compress

result = compress([
    {"role": "user", "content": "analyze this log output"},
    {"role": "user", "content": large_log_string},
])
print(f"Saved {result.compression_ratio:.0%} tokens")
```

## Proof

**Compression on real content types:**

| Content Type | Before | After | Savings |
|---|---:|---:|---:|
| JSON arrays (100 items) | 3,163 | 297 | **90.6%** |
| Build logs (200 lines) | 2,412 | 148 | **93.9%** |
| Shell output (200 lines) | 3,238 | 469 | **85.5%** |
| JSON arrays (500 items) | 9,526 | 1,614 | **83.1%** |
| Repeated tool outputs | 10,000 | 1,500 | **85%** |
| Git diffs | 3,000 | 300 | **90%** |

**Accuracy preserved:**

| Benchmark | Baseline | Copium | Delta |
|---|---:|---:|---|
| HTML Extraction (F1) | 0.958 | 0.919 | -0.039 |
| HTML Recall | -- | **0.982** | 98.2% content preserved |
| JSON Needle Finding | 4/4 | **4/4** | 100% accuracy at 87.6% compression |
| GSM8K (Math) | 0.870 | **0.870** | +/-0.000 |
| TruthfulQA (Factual) | 0.530 | **0.560** | +0.030 |

Reproduce: `pip install "copium-ai[evals]" && pytest tests/test_evals/ -v -s`

**Production telemetry** (250+ instances, 50K+ sessions):

| Metric | Value |
|---|---|
| Median proxy overhead | **52ms** |
| Total tokens saved | **1.4 billion** |
| Median compression (all requests) | 4.8% |
| Heavy tool-use sessions | **40-80%** |

Most requests are short conversational turns (median 4.8% compression). Long agent sessions with accumulated tool outputs, logs, and search results see the real savings (40-94%).

## When to use / When to skip

**Great fit if you...**
- Run AI coding agents daily and want savings without changing your code
- Use local LLMs and need to stay within context limits
- Work with verbose tool outputs (logs, JSON, search results, diffs)
- Want to extend context window life on quantized models

**Skip it if you...**
- Only send short conversational prompts (median savings: 4.8%)
- Already use a provider's native compaction and don't need more
- Work in a sandboxed environment where local processes can't run

## Compared to

Copium runs **locally**, covers **every** content type, works with every major framework, and supports both cloud and local LLMs.

| | Scope | Deploy | Local LLMs | Reversible |
|---|---|---|:---:|:---:|
| **Copium** | All context -- tools, RAG, logs, files, history | Proxy, library, MCP | Yes | Yes (CCR) |
| [Headroom](https://github.com/chopratejas/headroom) | All context | Proxy, library, middleware, MCP | No | Yes (CCR) |
| [RTK](https://github.com/rtk-ai/rtk) | CLI command outputs | CLI wrapper | Yes | No |
| [lean-ctx](https://github.com/yvgude/lean-ctx) | CLI commands, MCP tools | CLI wrapper, MCP | Yes | No |
| [Compresr](https://compresr.ai), [Token Co.](https://thetokencompany.ai) | Text sent to their API | Hosted API call | No | No |
| OpenAI Compaction | Conversation history | Provider-native | No | No |

### vs Headroom

Both Copium and Headroom compress AI agent context. Key differences:

| | Copium | Headroom |
|---|---|---|
| **Local LLM support** | Yes (Ollama, VLLM, llama.cpp) | No |
| **KV cache precision detection** | Yes (auto-detect Q4_0/Q8_0/FP16) | No |
| **Context paging** | Yes (Pichay-proven virtual memory) | No |
| **Telemetry** | Off by default (opt-in) | On by default (opt-out) |
| **CCR integrity checks** | Yes (SHA-256 verification) | No |
| **CCR retry logic** | Yes (exponential backoff) | No |
| **Windows support** | Pre-built wheels (CI tested) | Manual install only |
| **CCR debugging CLI** | Yes (`copium ccr list/inspect/verify`) | No |
| **Pricing** | Free, open-source (Apache 2.0) | Free, open-source (Apache 2.0) |
| **Language** | Python + Rust core | Python + Rust core |

### vs Provider-native compaction

Provider compaction (OpenAI, Anthropic) only compresses conversation history. Copium compresses **everything** -- tool outputs, logs, RAG results, files -- and routes each content type to the best compressor.

<details>
<summary><b>Integrations -- drop Copium into any stack</b></summary>

| Your setup | Hook in with |
|---|---|
| Any Python app | `compress(messages)` |
| Anthropic / OpenAI SDK | `CopiumClient(original_client=...)` |
| Vercel AI SDK | Copium middleware |
| LiteLLM | Callback integration |
| LangChain | `CopiumChatModel(your_llm)` |
| Agno | `CopiumAgnoModel(your_model)` |
| MCP clients | `pip install "copium-ai[mcp]"` |
| Any HTTP client | `copium run` (proxy mode) |

</details>

<details>
<summary><b>Pipeline transforms</b></summary>

| Transform | What it does | Savings |
|---|---|---|
| **SmartCrusher** | Compresses repeated tool outputs, diffs, JSON arrays | 40-95% |
| **Content Router** | Routes content to the best compressor | 20-60% |
| **Session Dedup** | Eliminates re-sent file content across turns | 30-70% |
| **Error Compressor** | Compacts stack traces into structured error cards | 50-80% |
| **Output Compressor** | Trims verbose assistant responses | 15-40% |
| **TOON Encoder** | Encodes uniform JSON arrays into pipe-delimited tables | 15-40% |
| **Cache Aligner** | Stabilizes prefix caching for better hit rates | 10-20% |
| **Differential Response** | Sends diffs for repeated tool calls | Up to 95% |

</details>

<details>
<summary><b>Local LLM features</b></summary>

Copium is built for local LLM users who face the **precision cliff**:

```
Q4_0 KV Cache at 32K context = 2% accuracy (vs 37.9% for FP16)
```

- **KV Cache-Aware Compression** -- auto-detects precision, scales aggressiveness
- **Cold/Hot Context Paging** -- virtual memory for LLM context (93% reduction)
- **Native Backend Integration** -- deep support for Ollama, VLLM, llama.cpp

```bash
copium doctor    # detect your setup and get recommendations
```

</details>

<details>
<summary><b>Configuration</b></summary>

Create `copium.json` in your project root:

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
```

</details>

<details>
<summary><b>Architecture</b></summary>

```
Request -> Cache Aligner -> Differential Response -> Session Dedup
       -> KV Cache Detection -> Content Router -> Error Compressor
       -> Paging -> Output Compressor -> TOON Encoder -> Provider
```

</details>

## Documentation

| Start here | Go deeper |
|---|---|
| [Quickstart](https://copium-docs.vercel.app/docs/quickstart) | [Architecture](https://copium-docs.vercel.app/docs/architecture) |
| [Proxy](https://copium-docs.vercel.app/docs/proxy) | [How compression works](https://copium-docs.vercel.app/docs/compression) |
| [MCP tools](https://copium-docs.vercel.app/docs/mcp) | [Benchmarks](https://copium-docs.vercel.app/docs/benchmarks) |
| [Configuration](https://copium-docs.vercel.app/docs/configuration) | [Limitations](https://copium-docs.vercel.app/docs/limitations) |

## Contributing

```bash
git clone https://github.com/iKislay/copium.git && cd copium
uv sync && uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache 2.0 -- see [LICENSE](LICENSE).

## Acknowledgments

- **Pichay** (arXiv:2603.09023) -- Virtual memory paging for LLM context
- **SmartCrusher** -- Differential compression for repeated tool outputs
- **ContextZip** -- Session-level deduplication (85.8% re-sent content)
- The **r/LocalLLaMA** community -- For identifying the precision cliff problem
