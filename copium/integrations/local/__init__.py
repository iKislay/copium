"""Local model integrations for Copium.

Provides auto-detection and configuration for local LLM backends:
- Ollama (localhost:11434)
- llama.cpp server (localhost:8080)
- LM Studio (localhost:1234)

Also includes:
- VRAM monitoring (NVIDIA, AMD, Apple Silicon)
- Adaptive compression (scales with available resources)
- Streaming compression (minimal memory footprint)
- Local triage engine (route simple tasks locally, complex to cloud)
- Hardware presets (8GB, 12GB, 16GB, 24GB configurations)

Usage:
    from copium.integrations.local import detect_local_backends
    backends = detect_local_backends()
    # Returns list of detected LocalBackendInfo objects

    from copium.integrations.local import OllamaIntegration
    ollama = OllamaIntegration()
    if ollama.detect():
        config = ollama.get_proxy_config()

    from copium.integrations.local import AdaptiveCompressor
    compressor = AdaptiveCompressor()
    config = compressor.get_config_for_context(context_size=8192)
"""

from copium.integrations.local.adaptive import AdaptiveCompressor, AdaptiveConfig
from copium.integrations.local.llamacpp import LlamaCppIntegration
from copium.integrations.local.lmstudio import LMStudioIntegration
from copium.integrations.local.ollama import OllamaIntegration
from copium.integrations.local.presets import (
    PRESETS,
    VRAMConstrainedPreset,
    get_preset_for_vram,
)
from copium.integrations.local.registry import (
    LocalBackendInfo,
    detect_local_backends,
)
from copium.integrations.local.streaming import StreamingCompressor
from copium.integrations.local.triage import LocalTriageEngine, RouteDecision
from copium.integrations.local.vram_monitor import VRAMMonitor, VRAMStatus

__all__ = [
    "AdaptiveCompressor",
    "AdaptiveConfig",
    "detect_local_backends",
    "get_preset_for_vram",
    "LlamaCppIntegration",
    "LMStudioIntegration",
    "LocalBackendInfo",
    "LocalTriageEngine",
    "OllamaIntegration",
    "PRESETS",
    "RouteDecision",
    "StreamingCompressor",
    "VRAMConstrainedPreset",
    "VRAMMonitor",
    "VRAMStatus",
]
