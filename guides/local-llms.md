# Using Copium with Local LLMs

> Copium is the **compression layer for local AI**. No cloud API keys required. Make your 8GB GPU act like 24GB and your 32K context feel like 128K.

## Why Local Models Need Copium

For cloud models, compression saves money. For local models, compression makes the agent **functional**:

- A 7B model on 8GB GPU can only hold 8K-32K context
- System prompts alone eat 25-100% of that budget
- After 5 tool calls, your agent is full and starts hallucinating
- Copium keeps your agent in the "Smart Zone" (0-40% utilization)

## Supported Backends

| Backend | Status | Auto-Detection | Default Port |
|---------|--------|----------------|--------------|
| Ollama | ✅ Full | Yes | 11434 |
| llama.cpp | ✅ Full | Yes | 8080 |
| LM Studio | ✅ Full | Yes | 1234 |
| VLLM | ✅ Full | Yes | 8000 |
| Any OpenAI-compatible | ✅ Full | Yes | configurable |

## Quick Start

### One-Command Setup

```bash
# Auto-detect all running local backends
copium doctor

# Configure for specific backend
copium wrap ollama
copium wrap llamacpp
copium wrap lmstudio
```

### Ollama

```bash
# 1. Install Ollama (https://ollama.ai)
curl -fsSL https://ollama.ai/install.sh | sh

# 2. Pull a model
ollama pull qwen3:8b

# 3. Start Copium with Ollama
copium wrap ollama
```

### llama.cpp

```bash
# 1. Start llama.cpp server
./llama-server -m models/qwen3-8b-q4_k_m.gguf --ctx-size 32768

# 2. Start Copium with llama.cpp
copium wrap llamacpp
```

### LM Studio

```bash
# 1. Load a model in LM Studio (GUI)
# 2. Start Copium with LM Studio
copium wrap lmstudio
```

## Programmatic Usage

### Auto-Detection

```python
from copium.integrations.local import detect_local_backends

backends = detect_local_backends()
for backend in backends:
    print(f"{backend.backend_type}: {backend.url} ({backend.model})")
    config = backend.get_proxy_config()
```

### Ollama

```python
from copium.integrations.local import OllamaIntegration

ollama = OllamaIntegration()
if ollama.detect():
    models = ollama.list_models()
    config = ollama.get_proxy_config(model="qwen3:8b")
```

### llama.cpp

```python
from copium.integrations.local import LlamaCppIntegration

llamacpp = LlamaCppIntegration()
if llamacpp.detect():
    info = llamacpp.get_server_info()
    utilization = llamacpp.get_context_utilization()
    config = llamacpp.get_proxy_config()
```

### LM Studio

```python
from copium.integrations.local import LMStudioIntegration

lmstudio = LMStudioIntegration()
if lmstudio.detect():
    model = lmstudio.get_active_model()
    config = lmstudio.get_proxy_config(model=model.id)
```

## VRAM-Aware Compression

Copium monitors your GPU and adapts compression automatically:

```python
from copium.integrations.local import AdaptiveCompressor

compressor = AdaptiveCompressor()
config = compressor.get_config()
# Returns: light (>50% VRAM free), standard (>30%), aggressive (>15%), maximum (<15%)
```

### Hardware Presets

```python
from copium.integrations.local import get_preset_for_vram, PRESETS

# Auto-select based on VRAM
preset = get_preset_for_vram(vram_mb=8192)

# Named presets: "8gb", "12gb", "16gb", "24gb"
preset = PRESETS["8gb"]
config = preset.to_proxy_config()
```

## KV Cache Optimization

Copium automatically detects KV cache precision and optimizes accordingly:

| Precision | Accuracy at 32K | Copium Strategy |
|-----------|-----------------|-----------------|
| FP16 | 95% | Conservative (compress less) |
| Q8_0 | 85% | Moderate (standard compression) |
| Q4_0 | 2% | Adaptive (aggressive before cliff) |

Detection is automatic via environment variables, backend APIs, or explicit config.

## Smart Routing (Triage)

Route simple tasks locally (free), compress complex tasks for cloud:

```python
from copium.integrations.local import LocalTriageEngine

engine = LocalTriageEngine(
    local_model="qwen3:8b",
    cloud_model="claude-sonnet-4-20250514",
)
decision = await engine.route(messages)
# Saves 40-79% cloud tokens on coding workloads
```

## Streaming Compression

For extreme memory constraints, process context chunk-by-chunk:

```python
from copium.integrations.local import StreamingCompressor

compressor = StreamingCompressor(chunk_size=4096)
for chunk in compressor.compress_iter(large_context):
    process(chunk.content)
print(f"Saved: {compressor.stats.savings_pct:.1f}%")
```

## Environment Variables

```bash
# Backend selection
COPIUM_BACKEND=ollama          # or llamacpp, lmstudio, vllm

# KV cache type (auto-detected if not set)
OLLAMA_KV_CACHE_TYPE=q4_0
LLAMA_CPP_KV_CACHE_TYPE=q8_0
VLLM_KV_CACHE_DTYPE=fp8

# Custom backend URLs
COPIUM_OLLAMA_URL=http://localhost:11434
COPIUM_LLAMACPP_URL=http://localhost:8080
COPIUM_LMSTUDIO_URL=http://localhost:1234

# Skip API key validation for local-only setups
COPIUM_LOCAL_LLM=true
```

## Troubleshooting

### "Connection refused" error
- Ensure your local LLM server is running
- Check the API URL and port are correct
- Verify the port is not blocked by firewall

### "Model not found" error
- Ensure the model is pulled/downloaded
- Check the model name matches exactly (`ollama list`)

### Slow performance
- Check VRAM pressure: `nvidia-smi` or `rocm-smi`
- Use a hardware preset: `copium wrap ollama --preset 8gb`
- Enable streaming compression for large contexts

### Agent "forgets" instructions
- Check context utilization: above 40% = leaving Smart Zone
- Enable more aggressive compression
- Consider smaller context window with more compression
