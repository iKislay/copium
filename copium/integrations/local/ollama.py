"""Ollama integration for Copium.

Auto-detects running Ollama instances, queries model info, and configures
the Copium proxy for optimal compression with local models.

Detection: checks http://localhost:11434/api/tags
Model info: queries /api/show for context length, quantization, parameters
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


@dataclass
class OllamaModelInfo:
    """Information about a loaded Ollama model."""

    name: str
    context_length: int = 4096
    quantization: str = "unknown"
    parameter_size: str = "unknown"
    family: str = "unknown"
    format: str = "unknown"
    capabilities: list[str] = field(default_factory=list)


class OllamaIntegration:
    """Auto-detect and configure Copium for Ollama.

    Usage:
        integration = OllamaIntegration()
        if integration.detect():
            models = integration.list_models()
            config = integration.get_proxy_config(model=models[0].name)
    """

    def __init__(self, base_url: str = _DEFAULT_OLLAMA_URL, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def detect(self) -> bool:
        """Check if Ollama is running locally."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def list_models(self) -> list[OllamaModelInfo]:
        """List available models from Ollama."""
        import json
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return []

        models = []
        for model_data in data.get("models", []):
            name = model_data.get("name", "")
            details = model_data.get("details", {})
            models.append(
                OllamaModelInfo(
                    name=name,
                    quantization=details.get("quantization_level", "unknown"),
                    parameter_size=details.get("parameter_size", "unknown"),
                    family=details.get("family", "unknown"),
                    format=details.get("format", "unknown"),
                )
            )
        return models

    def get_model_info(self, model: str) -> OllamaModelInfo | None:
        """Get detailed info for a specific model via /api/show."""
        import json
        import urllib.request
        import urllib.error

        try:
            payload = json.dumps({"name": model}).encode()
            req = urllib.request.Request(
                f"{self.base_url}/api/show",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

        details = data.get("details", {})
        model_info = data.get("model_info", {})

        # Extract context length from modelfile parameters
        context_length = 4096
        parameters = data.get("parameters", "")
        if isinstance(parameters, str):
            for line in parameters.split("\n"):
                if "num_ctx" in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            context_length = int(parts[-1])
                        except ValueError:
                            pass

        # Try model_info for context length
        for key, value in model_info.items():
            if "context_length" in key:
                try:
                    context_length = int(value)
                except (ValueError, TypeError):
                    pass

        capabilities = []
        if data.get("template") and "tool" in data.get("template", "").lower():
            capabilities.append("tools")

        return OllamaModelInfo(
            name=model,
            context_length=context_length,
            quantization=details.get("quantization_level", "unknown"),
            parameter_size=details.get("parameter_size", "unknown"),
            family=details.get("family", "unknown"),
            format=details.get("format", "unknown"),
            capabilities=capabilities,
        )

    def get_proxy_config(self, model: str | None = None) -> dict[str, Any]:
        """Generate proxy configuration optimized for Ollama.

        Returns a dict suitable for passing to ProxyConfig or CLI flags.
        """
        info = None
        if model:
            info = self.get_model_info(model)

        context_length = info.context_length if info else 4096
        aggressiveness = self._calc_aggressiveness(context_length)

        config: dict[str, Any] = {
            "backend": "anyllm",
            "anyllm_provider": "ollama",
            "openai_api_url": f"{self.base_url}/v1",
            "context_window": context_length,
            "optimize": True,
            "compression_aggressiveness": aggressiveness,
            "smart_zone_target": int(context_length * 0.4),
            "transforms": self._select_transforms(context_length),
        }

        if info and info.quantization.startswith("Q4"):
            config["kv_cache_precision"] = "q4_0"
            config["compression_aggressiveness"] = "aggressive"

        return config

    def _calc_aggressiveness(self, context_length: int) -> str:
        """Calculate compression aggressiveness based on context window."""
        if context_length <= 8192:
            return "aggressive"
        elif context_length <= 32768:
            return "standard"
        else:
            return "light"

    def _select_transforms(self, context_length: int) -> list[str]:
        """Select transforms based on available context."""
        # Always include core transforms
        transforms = ["SmartCrusher", "SessionDedup"]

        if context_length <= 32768:
            transforms.extend(["ErrorCompressor", "LogCompressor", "DiffCompressor"])

        if context_length <= 8192:
            transforms.append("SearchCompressor")

        return transforms
