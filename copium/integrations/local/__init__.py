"""Local model integrations for Copium.

Provides auto-detection and configuration for local LLM backends:
- Ollama (localhost:11434)
- llama.cpp server (localhost:8080)
- LM Studio (localhost:1234)

Usage:
    from copium.integrations.local import detect_local_backends
    backends = detect_local_backends()
    # Returns list of detected LocalBackendInfo objects

    from copium.integrations.local import OllamaIntegration
    ollama = OllamaIntegration()
    if ollama.detect():
        config = ollama.configure_proxy()
"""

from copium.integrations.local.ollama import OllamaIntegration
from copium.integrations.local.llamacpp import LlamaCppIntegration
from copium.integrations.local.lmstudio import LMStudioIntegration
from copium.integrations.local.registry import (
    LocalBackendInfo,
    detect_local_backends,
)

__all__ = [
    "OllamaIntegration",
    "LlamaCppIntegration",
    "LMStudioIntegration",
    "LocalBackendInfo",
    "detect_local_backends",
]
