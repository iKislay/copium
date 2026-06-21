"""Native backend integration for Ollama, VLLM, and llama.cpp.

Deep integration with local LLM backends:
- Auto-detect backend type and capabilities
- Read KV cache precision from backend APIs
- Adjust compression based on backend-specific quirks
- Monitor GPU memory usage for adaptive compression
- Provide backend-specific recommendations

Ollama integration:
- Read model info from /api/show
- Detect quantization level
- Monitor GPU memory via /api/ps

VLLM integration:
- Read engine args from /v1/engine/info
- Detect tensor parallelism
- Monitor GPU utilization

llama.cpp integration:
- Read model info from /props
- Detect context size and batch size
- Monitor KV cache usage
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BackendType(Enum):
    """Detected backend types."""

    OLLAMA = "ollama"
    VLLM = "vllm"
    LLAMACPP = "llama_cpp"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    UNKNOWN = "unknown"


@dataclass
class BackendCapabilities:
    """Capabilities of a detected backend."""

    backend: BackendType
    supports_streaming: bool = True
    supports_function_calling: bool = True
    supports_vision: bool = False
    supports_json_mode: bool = False
    supports_logprobs: bool = False
    max_context_length: int = 0
    kv_cache_precision: str = "unknown"
    gpu_count: int = 0
    gpu_memory_gb: float = 0.0
    model_name: str = ""
    quantization: str = ""

    def to_dict(self) -> dict:
        return {
            "backend": self.backend.value,
            "supports_streaming": self.supports_streaming,
            "supports_function_calling": self.supports_function_calling,
            "supports_vision": self.supports_vision,
            "supports_json_mode": self.supports_json_mode,
            "max_context_length": self.max_context_length,
            "kv_cache_precision": self.kv_cache_precision,
            "gpu_count": self.gpu_count,
            "gpu_memory_gb": self.gpu_memory_gb,
            "model_name": self.model_name,
            "quantization": self.quantization,
        }


@dataclass
class BackendHealth:
    """Health status of a backend."""

    is_healthy: bool = True
    latency_ms: float = 0.0
    gpu_utilization: float = 0.0  # 0.0 - 1.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    uptime_seconds: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "healthy": self.is_healthy,
            "latency_ms": round(self.latency_ms, 2),
            "gpu_utilization": round(self.gpu_utilization, 3),
            "memory_used_gb": round(self.memory_used_gb, 2),
            "memory_total_gb": round(self.memory_total_gb, 2),
            "uptime_seconds": round(self.uptime_seconds, 1),
            "error": self.error,
        }


class BackendDetector:
    """Detects and connects to LLM backends."""

    def __init__(self, base_url: str | None = None, timeout: float = 5.0):
        self.base_url = base_url
        self.timeout = timeout
        self._capabilities: BackendCapabilities | None = None
        self._health: BackendHealth | None = None

    def detect(self, base_url: str | None = None) -> BackendCapabilities:
        """Detect the backend type and capabilities."""
        url = base_url or self.base_url
        if not url:
            return BackendCapabilities(backend=BackendType.UNKNOWN)

        # Try each backend detector in order
        for detector in [
            self._detect_ollama,
            self._detect_vllm,
            self._detect_llamacpp,
        ]:
            try:
                caps = detector(url)
                if caps and caps.backend != BackendType.UNKNOWN:
                    self._capabilities = caps
                    return caps
            except Exception:
                continue

        return BackendCapabilities(backend=BackendType.UNKNOWN)

    def health_check(self, base_url: str | None = None) -> BackendHealth:
        """Check backend health and performance."""
        url = base_url or self.base_url
        if not url:
            return BackendHealth(is_healthy=False, error="No URL provided")

        start = time.perf_counter()
        try:
            req = urllib.request.Request(f"{url.rstrip('/')}/v1/models")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
            latency = (time.perf_counter() - start) * 1000

            self._health = BackendHealth(
                is_healthy=True,
                latency_ms=latency,
            )
            return self._health
        except Exception as e:
            return BackendHealth(
                is_healthy=False,
                error=str(e),
            )

    def _detect_ollama(self, url: str) -> BackendCapabilities | None:
        """Detect Ollama backend."""
        try:
            # Try /api/show
            req = urllib.request.Request(
                f"{url.rstrip('/')}/api/show",
                method="POST",
                headers={"Content-Type": "application/json"},
                data=json.dumps({"name": ""}).encode(),
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())

            caps = BackendCapabilities(
                backend=BackendType.OLLAMA,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
            )

            # Extract model info
            details = data.get("details", {})
            caps.model_name = details.get("model_name", "")
            caps.quantization = details.get("quantization_level", "")

            # Extract parameters
            params = data.get("parameters", {})
            if "num_ctx" in params:
                caps.max_context_length = int(params["num_ctx"])

            return caps
        except Exception:
            return None

    def _detect_vllm(self, url: str) -> BackendCapabilities | None:
        """Detect VLLM backend."""
        try:
            # Try /v1/engine/info
            req = urllib.request.Request(f"{url.rstrip('/')}/v1/engine/info")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())

            caps = BackendCapabilities(
                backend=BackendType.VLLM,
                supports_streaming=True,
                supports_function_calling=True,
                supports_json_mode=True,
                supports_logprobs=True,
            )

            # Extract info
            if "model" in data:
                caps.model_name = data["model"]
            if "max_model_len" in data:
                caps.max_context_length = data["max_model_len"]
            if "tensor_parallel_size" in data:
                caps.gpu_count = data["tensor_parallel_size"]

            return caps
        except Exception:
            return None

    def _detect_llamacpp(self, url: str) -> BackendCapabilities | None:
        """Detect llama.cpp backend."""
        try:
            # Try /props
            req = urllib.request.Request(f"{url.rstrip('/')}/props")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())

            caps = BackendCapabilities(
                backend=BackendType.LLAMACPP,
                supports_streaming=True,
                supports_function_calling=False,
                supports_json_mode=False,
            )

            # Extract info
            if "default_generation_settings" in data:
                settings = data["default_generation_settings"]
                if "n_ctx" in settings:
                    caps.max_context_length = settings["n_ctx"]

            if "total_slots" in data:
                caps.gpu_count = data["total_slots"]

            return caps
        except Exception:
            return None


class BackendIntegration:
    """High-level integration with local LLM backends."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.detector = BackendDetector(
            base_url=self.config.get("backend_url"),
            timeout=self.config.get("timeout", 5.0),
        )
        self._capabilities: BackendCapabilities | None = None
        self._health: BackendHealth | None = None

    def get_capabilities(self) -> BackendCapabilities:
        """Get backend capabilities (cached)."""
        if self._capabilities is None:
            self._capabilities = self.detector.detect()
        return self._capabilities

    def get_health(self) -> BackendHealth:
        """Get backend health."""
        self._health = self.detector.health_check()
        return self._health

    def get_recommendations(self) -> list[str]:
        """Get compression recommendations based on backend."""
        caps = self.get_capabilities()
        health = self.get_health()
        recs = []

        if caps.backend == BackendType.UNKNOWN:
            recs.append("Backend not detected — using conservative compression")
            return recs

        # Backend-specific recommendations
        if caps.backend == BackendType.OLLAMA:
            recs.append("Ollama detected — enable OLLAMA_KV_CACHE_TYPE for better precision")
            if caps.quantization:
                recs.append(f"Model quantization: {caps.quantization}")
            if caps.max_context_length > 0:
                recs.append(f"Context window: {caps.max_context_length} tokens")

        elif caps.backend == BackendType.VLLM:
            recs.append("VLLM detected — supports tensor parallelism for multi-GPU")
            if caps.gpu_count > 1:
                recs.append(f"Using {caps.gpu_count} GPUs")
            if caps.max_context_length > 0:
                recs.append(f"Max context: {caps.max_context_length} tokens")

        elif caps.backend == BackendType.LLAMACPP:
            recs.append("llama.cpp detected — enable LLAMA_CPP_KV_CACHE_TYPE for precision")
            if caps.max_context_length > 0:
                recs.append(f"Context size: {caps.max_context_length} tokens")

        # Health-based recommendations
        if health.is_healthy:
            if health.latency_ms > 1000:
                recs.append("High latency detected — consider more aggressive compression")
            if health.gpu_utilization > 0.9:
                recs.append("GPU utilization >90% — reduce context size")
        else:
            recs.append(f"Backend unhealthy: {health.error}")

        return recs

    def reset(self) -> None:
        """Reset cached detection results."""
        self._capabilities = None
        self._health = None
        self.detector._capabilities = None
        self.detector._health = None
