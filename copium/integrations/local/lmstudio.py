"""LM Studio integration for Copium.

Auto-detects running LM Studio instances and configures Copium
for optimal compression with locally hosted models.

Detection: checks http://localhost:1234/v1/models
LM Studio exposes an OpenAI-compatible API on port 1234 by default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LMSTUDIO_URL = "http://localhost:1234"


@dataclass
class LMStudioModelInfo:
    """Information about a model loaded in LM Studio."""

    id: str = "unknown"
    object: str = "model"
    owned_by: str = "local"
    context_length: int = 4096


class LMStudioIntegration:
    """Auto-detect and configure Copium for LM Studio.

    LM Studio exposes an OpenAI-compatible API, so configuration
    is straightforward — point the proxy at localhost:1234/v1.

    Usage:
        integration = LMStudioIntegration()
        if integration.detect():
            models = integration.list_models()
            config = integration.get_proxy_config()
    """

    def __init__(self, base_url: str = _DEFAULT_LMSTUDIO_URL, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def detect(self) -> bool:
        """Check if LM Studio is running."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/models",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def list_models(self) -> list[LMStudioModelInfo]:
        """List models currently loaded in LM Studio."""
        import json
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/models",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return []

        models = []
        for model_data in data.get("data", []):
            models.append(
                LMStudioModelInfo(
                    id=model_data.get("id", "unknown"),
                    object=model_data.get("object", "model"),
                    owned_by=model_data.get("owned_by", "local"),
                )
            )
        return models

    def get_active_model(self) -> LMStudioModelInfo | None:
        """Get the currently active/loaded model."""
        models = self.list_models()
        return models[0] if models else None

    def get_proxy_config(self, model: str | None = None) -> dict[str, Any]:
        """Generate proxy configuration for LM Studio.

        LM Studio serves OpenAI-compatible API, so we configure
        the proxy to target it as an OpenAI-compatible backend.
        """
        # LM Studio doesn't expose context length via API
        # Default to conservative 8K assumption for local models
        context_length = 8192

        # Try to infer from model name
        if model:
            context_length = self._infer_context_length(model)

        aggressiveness = self._calc_aggressiveness(context_length)

        config: dict[str, Any] = {
            "backend": "anyllm",
            "anyllm_provider": "openai",
            "openai_api_url": f"{self.base_url}/v1",
            "context_window": context_length,
            "optimize": True,
            "compression_aggressiveness": aggressiveness,
            "smart_zone_target": int(context_length * 0.4),
            "transforms": self._select_transforms(context_length),
            "ccr_enabled": True,
            "ccr_storage": "memory",
        }

        return config

    def _infer_context_length(self, model_id: str) -> int:
        """Infer context length from model name patterns."""
        model_lower = model_id.lower()

        # Common context length indicators in model names
        if "128k" in model_lower:
            return 131072
        elif "64k" in model_lower:
            return 65536
        elif "32k" in model_lower:
            return 32768
        elif "16k" in model_lower:
            return 16384
        elif "8k" in model_lower:
            return 8192

        # Model family defaults
        if "qwen" in model_lower:
            return 32768
        elif "llama" in model_lower or "codellama" in model_lower:
            return 8192
        elif "mistral" in model_lower:
            return 32768
        elif "deepseek" in model_lower:
            return 32768
        elif "phi" in model_lower:
            return 4096
        elif "gemma" in model_lower:
            return 8192

        return 8192  # Conservative default

    def _calc_aggressiveness(self, context_length: int) -> str:
        """Calculate compression aggressiveness."""
        if context_length <= 8192:
            return "aggressive"
        elif context_length <= 32768:
            return "standard"
        else:
            return "light"

    def _select_transforms(self, context_length: int) -> list[str]:
        """Select transforms based on context budget."""
        transforms = ["SmartCrusher", "SessionDedup"]

        if context_length <= 32768:
            transforms.extend(["ErrorCompressor", "LogCompressor", "DiffCompressor"])

        if context_length <= 8192:
            transforms.append("SearchCompressor")

        return transforms
