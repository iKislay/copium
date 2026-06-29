"""llama.cpp server integration for Copium.

Auto-detects running llama.cpp server instances, queries server health
and slot information, and configures Copium for VRAM-constrained environments.

Detection: checks http://localhost:8080/health
Server info: queries /health and /slots for context usage and KV cache type
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LLAMACPP_URL = "http://localhost:8080"


@dataclass
class LlamaCppServerInfo:
    """Information about a llama.cpp server instance."""

    model: str = "unknown"
    context_size: int = 4096
    context_used: int = 0
    kv_cache_type: str = "f16"
    slots_available: int = 1
    slots_used: int = 0
    n_gpu_layers: int = 0


class LlamaCppIntegration:
    """Auto-detect and configure Copium for llama.cpp server.

    Connects to llama.cpp's HTTP server (llama-server or server binary)
    to query capabilities and configure compression.

    Usage:
        integration = LlamaCppIntegration()
        if integration.detect():
            info = integration.get_server_info()
            config = integration.get_proxy_config()
    """

    def __init__(self, server_url: str = _DEFAULT_LLAMACPP_URL, timeout: float = 3.0):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def detect(self) -> bool:
        """Check if llama.cpp server is running."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"{self.server_url}/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def get_server_info(self) -> LlamaCppServerInfo:
        """Query /health and /slots for server capabilities."""
        import json
        import urllib.request
        import urllib.error

        info = LlamaCppServerInfo()

        # Query /health
        try:
            req = urllib.request.Request(
                f"{self.server_url}/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                health = json.loads(resp.read())
                info.model = health.get("model", "unknown")
                if "slots_idle" in health:
                    info.slots_available = health.get("slots_idle", 1)
                if "slots_processing" in health:
                    info.slots_used = health.get("slots_processing", 0)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass

        # Query /slots for context usage
        try:
            req = urllib.request.Request(
                f"{self.server_url}/slots",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                slots = json.loads(resp.read())
                if isinstance(slots, list) and slots:
                    total_ctx = 0
                    total_used = 0
                    for slot in slots:
                        total_ctx = max(total_ctx, slot.get("n_ctx", 4096))
                        total_used += slot.get("n_past", 0)
                    info.context_size = total_ctx
                    info.context_used = total_used
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass

        # Query /props for additional info
        try:
            req = urllib.request.Request(
                f"{self.server_url}/props",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                props = json.loads(resp.read())
                if "default_generation_settings" in props:
                    settings = props["default_generation_settings"]
                    info.context_size = settings.get("n_ctx", info.context_size)
                    info.n_gpu_layers = settings.get("n_gpu_layers", 0)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass

        return info

    def get_proxy_config(self) -> dict[str, Any]:
        """Generate proxy configuration optimized for llama.cpp.

        Configures for constrained VRAM environments with appropriate
        compression and KV cache awareness.
        """
        info = self.get_server_info()
        ctx_size = info.context_size

        # Use 60% of context as soft limit (keep model in Smart Zone)
        soft_limit = int(ctx_size * 0.6)
        aggressiveness = self._calc_aggressiveness(ctx_size)

        config: dict[str, Any] = {
            "backend": "anyllm",
            "anyllm_provider": "openai",
            "openai_api_url": f"{self.server_url}/v1",
            "context_window": ctx_size,
            "soft_limit": soft_limit,
            "optimize": True,
            "compression_aggressiveness": aggressiveness,
            "smart_zone_target": int(ctx_size * 0.4),
            "transforms": self._select_transforms(ctx_size),
            "ccr_enabled": True,
            "ccr_storage": "memory",  # Avoid disk I/O for speed
        }

        # KV cache detection
        kv_type = self._detect_kv_cache_type(info)
        if kv_type:
            config["kv_cache_precision"] = kv_type

        return config

    def get_context_utilization(self) -> float:
        """Get current context utilization as a percentage (0.0-1.0)."""
        info = self.get_server_info()
        if info.context_size == 0:
            return 0.0
        return info.context_used / info.context_size

    def _detect_kv_cache_type(self, info: LlamaCppServerInfo) -> str | None:
        """Detect KV cache quantization type."""
        import os

        # Check environment variable first
        kv_env = os.environ.get("LLAMA_CPP_KV_CACHE_TYPE", "").lower()
        if kv_env:
            return kv_env

        # Check server-reported type
        if info.kv_cache_type and info.kv_cache_type != "f16":
            return info.kv_cache_type

        return None

    def _calc_aggressiveness(self, context_size: int) -> str:
        """Calculate compression aggressiveness."""
        if context_size <= 8192:
            return "aggressive"
        elif context_size <= 16384:
            return "standard"
        else:
            return "moderate"

    def _select_transforms(self, context_size: int) -> list[str]:
        """Select transforms for constrained environments."""
        transforms = [
            "SmartCrusher",
            "SessionDedup",
            "ErrorCompressor",
            "LogCompressor",
            "DiffCompressor",
        ]

        if context_size <= 16384:
            transforms.append("SearchCompressor")

        return transforms
