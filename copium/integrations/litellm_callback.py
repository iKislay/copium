"""LiteLLM callback — add Copium compression to LiteLLM with one line.

    # Local mode (compression runs in-process):
    import litellm
    from copium.integrations.litellm_callback import CopiumCallback

    litellm.callbacks = [CopiumCallback()]

    # Cloud mode (managed CCR, TOIN, analytics via Copium Cloud):
    litellm.callbacks = [CopiumCallback(api_key="hdr_xxx")]

Works with LiteLLM's completion(), acompletion(), and proxy modes.
Cloud mode requires httpx: pip install httpx
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CLOUD_URL = "https://api.copiumlabs.ai"


class CopiumCallback:
    """LiteLLM callback that compresses messages before each API call.

    Implements LiteLLM's CustomLogger interface (async_pre_call_hook).

    Two modes:
    - Local (default): Compresses in-process using copium.compress().
    - Cloud (api_key set): Calls Copium Cloud API for managed compression
      with org-scoped CCR, TOIN learning, and analytics dashboards.

    Usage (local):
        litellm.callbacks = [CopiumCallback()]

    Usage (cloud):
        litellm.callbacks = [CopiumCallback(api_key="hdr_xxx")]

    Usage (cloud with LiteLLM proxy config):
        # litellm_config.yaml
        litellm_settings:
          callbacks: [copium.integrations.litellm_callback.CopiumCallback]
        environment_variables:
          COPIUM_API_KEY: "hdr_xxx"
    """

    def __init__(
        self,
        min_tokens: int = 500,
        model_limit: int = 200000,
        hooks: Any = None,
        api_key: str | None = None,
        api_url: str | None = None,
    ) -> None:
        self._min_tokens = min_tokens
        self._model_limit = model_limit
        self._hooks = hooks
        self._total_saved = 0

        # Cloud mode: if api_key is set, compress via Copium Cloud API
        # Falls back to COPIUM_API_KEY env var
        import os

        self._api_key = api_key or os.environ.get("COPIUM_API_KEY", "").strip() or None
        self._api_url = (
            api_url or os.environ.get("COPIUM_API_URL", "").strip() or _DEFAULT_CLOUD_URL
        ).rstrip("/")
        self._client: Any = None  # Lazy-initialized httpx.AsyncClient

    @property
    def total_tokens_saved(self) -> int:
        """Total tokens saved across all calls."""
        return self._total_saved

    @property
    def cloud_mode(self) -> bool:
        """Whether cloud compression is enabled."""
        return self._api_key is not None

    async def async_pre_call_hook(
        self,
        user_api_key: str,
        data: dict[str, Any],
        call_type: str,
    ) -> dict[str, Any]:
        """Called by LiteLLM before each API call. Compresses messages."""
        if call_type not in ("completion", "acompletion"):
            return data

        messages = data.get("messages", [])
        model = data.get("model", "")

        if not messages:
            return data

        try:
            if self._api_key:
                result = await self._cloud_compress(messages, model)
            else:
                result = self._local_compress(messages, model)

            if result and result.get("tokens_saved", 0) > 0 and "messages" in result:
                data["messages"] = result["messages"]
                self._total_saved += result["tokens_saved"]
                logger.info(
                    "Copium%s: %d→%d tokens (saved %d, %.0f%%) [total saved: %d]",
                    " Cloud" if self._api_key else "",
                    result["tokens_before"],
                    result["tokens_after"],
                    result["tokens_saved"],
                    result.get("compression_ratio", 0) * 100,
                    self._total_saved,
                )

        except Exception as e:
            logger.warning("Copium compression failed, using original messages: %s", e)

        return data

    def _local_compress(self, messages: list[dict], model: str) -> dict[str, Any] | None:
        """Compress locally using copium.compress()."""
        from copium.compress import compress

        result = compress(
            messages=messages,
            model=model or "claude-sonnet-4-5-20250929",
            model_limit=self._model_limit,
            hooks=self._hooks,
        )
        return {
            "messages": result.messages,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "tokens_saved": result.tokens_saved,
            "compression_ratio": result.compression_ratio,
        }

    async def _cloud_compress(self, messages: list[dict], model: str) -> dict[str, Any] | None:
        """Compress via Copium Cloud API (managed CCR, TOIN, analytics)."""
        if self._client is None:
            try:
                import httpx
            except ImportError as e:
                raise ImportError(
                    "httpx is required for Copium Cloud mode: pip install httpx"
                ) from e
            self._client = httpx.AsyncClient(timeout=30.0)

        client = self._client
        assert client is not None
        resp = await client.post(
            f"{self._api_url}/v1/saas/compress",
            headers={
                "X-Copium-Key": self._api_key,
                "Content-Type": "application/json",
            },
            content=json.dumps(
                {
                    "messages": messages,
                    "model": model or "claude-sonnet-4-5-20250929",
                    "model_limit": self._model_limit,
                }
            ),
        )

        if resp.status_code != 200:
            logger.warning("Copium Cloud API error: %d %s", resp.status_code, resp.text[:200])
            return None

        result: dict[str, Any] = resp.json()
        return result

    async def async_success_handler(
        self, kwargs: dict, response: Any, start_time: Any, end_time: Any
    ) -> None:
        """Called after successful completion. No-op for now."""
        pass

    async def async_failure_handler(
        self, kwargs: dict, response: Any, start_time: Any, end_time: Any
    ) -> None:
        """Called after failed completion. No-op for now."""
        pass
