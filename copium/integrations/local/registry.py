"""Local backend detection registry.

Scans for all supported local LLM backends and provides a unified
interface for auto-configuration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from copium.integrations.local.ollama import OllamaIntegration
from copium.integrations.local.llamacpp import LlamaCppIntegration
from copium.integrations.local.lmstudio import LMStudioIntegration

logger = logging.getLogger(__name__)


class LocalBackendType(str, Enum):
    """Supported local backend types."""

    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"
    LMSTUDIO = "lmstudio"


@dataclass
class LocalBackendInfo:
    """Detected local backend with configuration."""

    backend_type: LocalBackendType
    url: str
    model: str | None = None
    context_length: int = 4096
    is_running: bool = False

    def get_proxy_config(self) -> dict[str, Any]:
        """Get the proxy configuration for this backend."""
        if self.backend_type == LocalBackendType.OLLAMA:
            integration = OllamaIntegration(base_url=self.url)
            return integration.get_proxy_config(model=self.model)
        elif self.backend_type == LocalBackendType.LLAMACPP:
            integration = LlamaCppIntegration(server_url=self.url)
            return integration.get_proxy_config()
        elif self.backend_type == LocalBackendType.LMSTUDIO:
            integration = LMStudioIntegration(base_url=self.url)
            return integration.get_proxy_config(model=self.model)
        return {}


def detect_local_backends(
    ollama_url: str = "http://localhost:11434",
    llamacpp_url: str = "http://localhost:8080",
    lmstudio_url: str = "http://localhost:1234",
) -> list[LocalBackendInfo]:
    """Scan for all running local LLM backends.

    Checks default ports for Ollama, llama.cpp, and LM Studio.
    Returns a list of detected backends with their capabilities.

    Args:
        ollama_url: URL to check for Ollama (default: localhost:11434)
        llamacpp_url: URL to check for llama.cpp (default: localhost:8080)
        lmstudio_url: URL to check for LM Studio (default: localhost:1234)

    Returns:
        List of LocalBackendInfo for each detected backend.
    """
    backends: list[LocalBackendInfo] = []

    # Check Ollama
    ollama = OllamaIntegration(base_url=ollama_url)
    if ollama.detect():
        models = ollama.list_models()
        model_name = models[0].name if models else None
        context_length = 4096

        if model_name:
            info = ollama.get_model_info(model_name)
            if info:
                context_length = info.context_length

        backends.append(
            LocalBackendInfo(
                backend_type=LocalBackendType.OLLAMA,
                url=ollama_url,
                model=model_name,
                context_length=context_length,
                is_running=True,
            )
        )
        logger.info("Detected Ollama at %s (model: %s)", ollama_url, model_name)

    # Check llama.cpp
    llamacpp = LlamaCppIntegration(server_url=llamacpp_url)
    if llamacpp.detect():
        info = llamacpp.get_server_info()
        backends.append(
            LocalBackendInfo(
                backend_type=LocalBackendType.LLAMACPP,
                url=llamacpp_url,
                model=info.model,
                context_length=info.context_size,
                is_running=True,
            )
        )
        logger.info("Detected llama.cpp at %s (model: %s)", llamacpp_url, info.model)

    # Check LM Studio
    lmstudio = LMStudioIntegration(base_url=lmstudio_url)
    if lmstudio.detect():
        active = lmstudio.get_active_model()
        model_id = active.id if active else None
        backends.append(
            LocalBackendInfo(
                backend_type=LocalBackendType.LMSTUDIO,
                url=lmstudio_url,
                model=model_id,
                context_length=lmstudio._infer_context_length(model_id or ""),
                is_running=True,
            )
        )
        logger.info("Detected LM Studio at %s (model: %s)", lmstudio_url, model_id)

    if not backends:
        logger.info(
            "No local backends detected. Checked: Ollama (%s), "
            "llama.cpp (%s), LM Studio (%s)",
            ollama_url,
            llamacpp_url,
            lmstudio_url,
        )

    return backends
