# Using Copium with Local LLMs

> Copium supports local LLMs out of the box. No cloud API keys required.

## Supported Backends

| Backend | Status | Auto-Detection | Notes |
|---------|--------|----------------|-------|
| Ollama | ✅ Full | Yes | Most popular local LLM backend |
| VLLM | ✅ Full | Yes | High-performance serving |
| llama.cpp | ✅ Full | Yes | Lightweight, CPU-focused |
| Hermes | ✅ Full | Yes | Via OpenAI-compatible endpoint |
| Any OpenAI-compatible | ✅ Full | Yes | Generic support |

## Quick Start

### Ollama

```bash
# 1. Install Ollama (https://ollama.ai)
curl -fsSL https://ollama.ai/install.sh | sh

# 2. Pull a model
ollama pull llama3

# 3. Start Copium with Ollama
copium run --backend ollama --model llama3
```

### VLLM

```bash
# 1. Install VLLM
pip install vllm

# 2. Start VLLM server
vllm serve meta-llama/Llama-3-8B-Instruct

# 3. Start Copium with VLLM
copium run --backend vllm --model meta-llama/Llama-3-8B-Instruct
```

### llama.cpp

```bash
# 1. Install llama.cpp
# Follow instructions at https://github.com/ggerganov/llama.cpp

# 2. Start llama.cpp server
./llama-server -m models/llama-3-8b-instruct.gguf

# 3. Start Copium with llama.cpp
copium run --backend llamacpp --model llama-3-8b-instruct
```

### Hermes

```bash
# Hermes works via any OpenAI-compatible endpoint
copium run --backend hermes --model hermes-3-llama-3.1-405b --api-url http://localhost:8080/v1
```

## KV Cache Optimization

Copium automatically detects KV cache precision and optimizes accordingly:

| Precision | Use Case | Optimization |
|-----------|----------|--------------|
| Q4_0 | Maximum compression | Aggressive prefix stabilization |
| Q8_0 | Balanced | Standard cache alignment |
| FP16 | Maximum quality | Conservative optimization |

The detection is automatic - no configuration needed.

## Environment Variables

```bash
# Backend selection
COPIUM_BACKEND=ollama          # or vllm, llamacpp, hermes

# Model selection
COPIUM_MODEL=llama3

# API URL (for custom endpoints)
COPIUM_API_URL=http://localhost:11434/v1

# Local LLM specific
COPIUM_LOCAL_LLM=true          # Skip API key validation
```

## Performance Tips

1. **Use local embeddings**: Copium can run embeddings locally via fastembed
2. **Enable KV cache optimization**: Automatic for local backends
3. **Adjust compression ratio**: Local models may benefit from less aggressive compression
   ```bash
   copium run --backend ollama --model llama3 --target-ratio 0.3
   ```

## Troubleshooting

### "Connection refused" error
- Ensure your local LLM server is running
- Check the API URL is correct
- Verify the port is not blocked by firewall

### "Model not found" error
- Ensure the model is pulled/downloaded
- Check the model name matches exactly

### Slow performance
- Reduce compression ratio: `--target-ratio 0.2`
- Use a smaller model for testing
- Check CPU/GPU utilization

## Examples

See the `examples/local-llms/` directory for complete working examples.
