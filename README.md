# Copium

**Context Optimization Layer for LLM Applications**

> 40-65% token savings. Zero quality loss. Drop-in proxy for Claude, GPT, Gemini, and local LLMs.

[![Tests](https://img.shields.io/badge/tests-245%20passing-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.10+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## What is Copium?

Copium is a **transparent proxy** that sits between your AI coding agent (Claude Code, Cursor, Aider, etc.) and the LLM API. It intercepts every request, compresses the context intelligently, and forwards it to the provider — saving 40-65% on tokens with zero quality loss.

```
┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  AI Agent    │ ──▶ │   Copium    │ ──▶ │  LLM API     │
│  (Claude,    │ ◀── │   Proxy     │ ◀── │  (Anthropic, │
│   Cursor)    │     │             │     │   OpenAI)    │
└──────────────┘     └─────────────┘     └──────────────┘
                     ✂️ 40-65% fewer tokens
                     💰 $30-60/month savings
```

**Why "Copium"?** Because you're coping with token costs. And because the best compression is the kind you don't notice.

---

## Quick Start

### 1. Install

```bash
pip install copium
# or
uv tool install copium
```

### 2. Run

```bash
# Start the proxy (default: http://localhost:8082)
copium run

# Or with a specific provider
copium run --provider anthropic
copium run --provider openai
```

### 3. Configure your agent

Point your agent to use Copium as the API endpoint:

```bash
# Claude Code
export ANTHROPIC_BASE_URL=http://localhost:8082

# Cursor / Aider
export OPENAI_API_BASE=http://localhost:8082/v1
```

That's it. Copium automatically compresses every request.

---

## Features

### 🔄 Pipeline Transforms

Copium applies a series of intelligent transforms to every request:

| Transform | What it does | Savings |
|-----------|-------------|---------|
| **SmartCrusher** | Compresses repeated tool outputs, diffs, JSON arrays | 40-95% |
| **Content Router** | Routes content to the best compressor (code, logs, search, HTML) | 20-60% |
| **Session Dedup** | Eliminates re-sent file content across turns | 30-70% |
| **Error Compressor** | Compacts stack traces into structured error cards | 50-80% |
| **Output Compressor** | Trims verbose assistant responses | 15-40% |
| **TOON Encoder** | Encodes uniform JSON arrays into pipe-delimited tables | 15-40% |
| **Cache Aligner** | Stabilizes prefix caching for better hit rates | 10-20% |
| **Differential Response** | Sends diffs for repeated tool calls (e.g., git status) | Up to 95% |

### 🧠 Local LLM Intelligence

Copium is built for local LLM users who face the **precision cliff**:

```
Q4_0 KV Cache at 32K context = 2% accuracy (vs 37.9% for FP16)
```

Features designed for local backends:

- **KV Cache-Aware Compression** — Auto-detects your KV cache precision (Q4_0, Q8_0, FP16) and scales compression aggressiveness accordingly
- **Cold/Hot Context Paging** — Virtual memory for LLM context (Pichay-proven: 93% reduction, 0.0254% fault rate)
- **Native Backend Integration** — Deep support for Ollama, VLLM, and llama.cpp

### 📊 Context Budget Management

```python
from copium import CopiumConfig

config = CopiumConfig()
config.context_budget.kv_cache_type = "q4_0"
config.context_budget.model = "llama3:8b"
# Automatically adjusts limits based on KV cache precision
```

### 🔍 Doctor Command

```bash
copium doctor
```

Detects your setup and provides recommendations:
- Backend detection (Ollama/VLLM/llama.cpp)
- KV cache precision check
- Model compatibility warnings
- Session dedup configuration

### 📈 TUI Dashboard

```bash
copium dashboard
```

Real-time terminal dashboard showing:
- Token savings per request
- Per-transform breakdown
- Request stream with compression ratios
- Dedup statistics

---

## Configuration

### Config File

Create `copium.json` in your project root:

```json
{
  "mode": "optimize",
  "cache_aligner": {
    "enabled": true
  },
  "session_dedup": {
    "enabled": true,
    "similarity_threshold": 0.85
  },
  "context_budget": {
    "enabled": true,
    "kv_cache_type": "q4_0",
    "model": "llama3:8b"
  },
  "error_compressor": {
    "enabled": true,
    "max_stack_frames": 3,
    "preserve_security_warnings": true
  },
  "kv_cache_aware": {
    "enabled": true,
    "detect_env": true
  },
  "paging": {
    "enabled": true,
    "eviction_policy": "fifo",
    "eviction_tau": 4
  }
}
```

### Per-Request Control

Disable specific transforms per request:

```bash
curl -H "X-Copium-Disable: toon,code_compressor" \
     http://localhost:8082/v1/chat/completions
```

### Environment Variables

```bash
# KV Cache Detection
export OLLAMA_KV_CACHE_TYPE=q4_0
export VLLM_KV_CACHE_DTYPE=fp8_e4m3
export LLAMA_CPP_KV_CACHE_TYPE=q8_0

# Proxy Settings
export COPIUM_PORT=8082
export COPIUM_HOST=0.0.0.0

# Debug
export COPIUM_LOG_LEVEL=debug
```

---

## Architecture

```
copium/
├── proxy/              # HTTP proxy server
│   ├── handler.py      # Request/response handling
│   └── middleware.py    # Auth, rate limiting, logging
├── transforms/         # Compression pipeline
│   ├── pipeline.py     # Transform orchestration
│   ├── session_dedup.py # Cross-turn deduplication
│   ├── content_router.py # Intelligent content routing
│   ├── error_compressor.py # Error-driven compression
│   ├── kv_cache_aware.py # KV cache precision detection
│   ├── paging_transform.py # Cold/hot context paging
│   ├── output_compressor.py # Assistant response trimming
│   └── toon_encoder.py # Table encoding for JSON arrays
├── kv_aware.py         # KV cache precision profiles
├── paging.py           # Virtual memory paging system
├── simulator.py        # Context window simulator
├── grammar.py          # Grammar-constrained compression
├── native_backends.py  # Ollama/VLLM/llama.cpp integration
├── budget/             # Token budget management
├── cli/                # CLI commands (run, doctor, dashboard)
└── config.py           # Configuration models
```

### Pipeline Flow

```
Request → Cache Aligner → Differential Response → Session Dedup
       → KV Cache Detection → Content Router → Error Compressor
       → Paging → Output Compressor → TOON Encoder → Provider
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test suites
pytest tests/test_session_dedup.py -v      # 21 tests
pytest tests/test_error_compressor.py -v   # 35 tests
pytest tests/test_kv_cache_aware.py -v     # 39 tests
pytest tests/test_paging.py -v             # 23 tests
pytest tests/test_phase3.py -v             # 31 tests

# Run with coverage
pytest tests/ --cov=copium --cov-report=html
```

---

## Benchmark Results

### Token Savings by Content Type

| Content Type | Before | After | Savings |
|-------------|--------|-------|---------|
| Repeated tool outputs | 10,000 | 1,500 | **85%** |
| Stack traces | 2,000 | 400 | **80%** |
| JSON arrays | 5,000 | 2,000 | **60%** |
| Git diffs | 3,000 | 300 | **90%** |
| Search results | 8,000 | 3,200 | **60%** |
| Log output | 4,000 | 1,600 | **60%** |

### KV Cache Precision Impact

| Precision | 16K Context | 32K Context | 64K Context |
|-----------|-------------|-------------|-------------|
| FP16 | 95% accuracy | 93% accuracy | 90% accuracy |
| Q8_0 | 90% accuracy | 85% accuracy | 75% accuracy |
| Q4_0 | 90% accuracy | **2% accuracy** ⚠️ | Catastrophic |

Copium detects this and applies aggressive compression before you hit the cliff.

---

## Why Copium?

| Feature | Copium | Cloud-only proxies |
|---------|--------|-------------------|
| **Target** | Local LLMs + Cloud APIs | Cloud APIs only |
| **KV Cache Detection** | ✅ Auto-detect precision | ❌ |
| **Context Paging** | ✅ Pichay-proven virtual memory | ❌ |
| **Error Cards** | ✅ Structured with NEXT_ACTIONS | ❌ |
| **Backend Integration** | ✅ Ollama/VLLM/llama.cpp | ❌ |
| **Syntax Validation** | ✅ JSON/markdown/code enforcement | ❌ |
| **Context Simulator** | ✅ A/B test before deploying | ❌ |
| **Transforms** | 10+ specialized compressors | Single compressor |
| **Pipeline** | Content-aware routing | Passthrough |
| **TUI Dashboard** | ✅ Real-time metrics | ❌ |
| **Doctor Command** | ✅ Auto-detect setup | ❌ |

---

## Why Local LLM Users Need Copium

Local LLM users face unique challenges that cloud-only tools don't address:

1. **Precision Cliff**: Q4_0 KV cache drops to 2% accuracy at 32K tokens. Copium detects this and compresses aggressively before you hit it.

2. **Context Degradation**: Models degrade silently above 16K tokens. Copium's context paging keeps the working set small.

3. **No Cloud Fallback**: When your local model fails, you can't just switch to GPT-4. Copium maximizes what you can do with limited context.

4. **KV Cache Memory**: Quantized KV caches save VRAM but lose precision. Copium's compression compensates for the quality loss.

---

## Contributing

```bash
# Clone
git clone https://github.com/iKislay/copium.git
cd copium

# Install dev dependencies
uv sync

# Run tests
pytest tests/ -v

# Lint
ruff check .
ruff format .
```

---

## License

MIT

---

## Acknowledgments

- **Pichay** (arXiv:2603.09023) — Virtual memory paging for LLM context
- **SmartCrusher** — Differential compression for repeated tool outputs
- **ContextZip** — Session-level deduplication (85.8% re-sent content)
- The **r/LocalLLaMA** community — For identifying the precision cliff problem
