"""Auto-batching for provider Batch APIs.

Batches requests and routes them to provider batch endpoints
for 50% discount. Supports OpenAI and Anthropic batch APIs.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from copium.config import CopiumConfig


@dataclass
class BatchRequest:
    """A single request in a batch."""

    request_id: str
    custom_id: str
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result of a batch request."""

    request_id: str
    custom_id: str
    response: dict[str, Any] | None = None
    error: str | None = None
    status: str = "pending"  # pending, processing, completed, failed


@dataclass
class AutoBatchConfig:
    """Configuration for auto-batching."""

    enabled: bool = False

    # Provider: "openai" or "anthropic"
    provider: str = "openai"

    # Batch size limits
    max_batch_size: int = 100  # OpenAI limit
    min_batch_size: int = 2  # Minimum for batch to be worth it

    # Timing
    batch_timeout_seconds: float = 60.0  # Max wait for batch to fill
    poll_interval_seconds: float = 5.0  # How often to check batch status

    # Eligibility: skip batch for these conditions
    skip_if_streaming: bool = True
    skip_if_tools: bool = False  # Some batch APIs don't support tools
    skip_if_max_tokens_over: int = 4096

    # Cost savings
    batch_discount: float = 0.5  # 50% discount on batch APIs


class AutoBatcher:
    """Manages batching of requests to provider batch APIs.

    Collects requests, forms batches, submits to batch API,
    polls for completion, and returns results.
    """

    def __init__(self, config: AutoBatchConfig | None = None) -> None:
        self.config = config or AutoBatchConfig()
        self._pending: list[BatchRequest] = []
        self._results: dict[str, BatchResult] = {}
        self._batch_id: str | None = None

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def is_eligible(self, request: dict[str, Any]) -> bool:
        """Check if a request is eligible for batch processing."""
        if not self.enabled:
            return False

        # Skip streaming requests
        if self.config.skip_if_streaming and request.get("stream", False):
            return False

        # Skip if tools present and batch doesn't support them
        if self.config.skip_if_tools and request.get("tools"):
            return False

        # Skip if max_tokens too high
        if self.config.skip_if_max_tokens_over:
            max_tokens = request.get("max_tokens", 0)
            if max_tokens > self.config.skip_if_max_tokens_over:
                return False

        return True

    def add_request(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Add a request to the pending batch. Returns request ID."""
        request_id = str(uuid.uuid4())
        custom_id = f"req-{request_id[:8]}"

        batch_request = BatchRequest(
            request_id=request_id,
            custom_id=custom_id,
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=kwargs,
        )

        self._pending.append(batch_request)
        return request_id

    def _format_openai_batch(self, requests: list[BatchRequest]) -> list[dict[str, Any]]:
        """Format requests for OpenAI Batch API."""
        batch = []
        for req in requests:
            body: dict[str, Any] = {
                "model": req.model,
                "messages": req.messages,
            }
            if req.tools:
                body["tools"] = req.tools
            if req.temperature is not None:
                body["temperature"] = req.temperature
            if req.max_tokens is not None:
                body["max_tokens"] = req.max_tokens

            batch.append({
                "custom_id": req.custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            })
        return batch

    def _format_anthropic_batch(self, requests: list[BatchRequest]) -> list[dict[str, Any]]:
        """Format requests for Anthropic Message Batches API."""
        batch = []
        for req in requests:
            params: dict[str, Any] = {
                "model": req.model,
                "messages": req.messages,
                "max_tokens": req.max_tokens or 4096,
            }
            if req.tools:
                params["tools"] = req.tools
            if req.temperature is not None:
                params["temperature"] = req.temperature

            batch.append({
                "custom_id": req.custom_id,
                "params": params,
            })
        return batch

    def get_batch_payload(self) -> list[dict[str, Any]] | None:
        """Get the current batch payload if ready to submit."""
        if len(self._pending) < self.config.min_batch_size:
            return None

        # Take up to max_batch_size requests
        batch_requests = self._pending[: self.config.max_batch_size]

        if self.config.provider == "openai":
            return self._format_openai_batch(batch_requests)
        elif self.config.provider == "anthropic":
            return self._format_anthropic_batch(batch_requests)
        return None

    def submit_batch(self) -> str | None:
        """Submit the current batch. Returns batch ID if submitted."""
        if not self._pending:
            return None

        self._batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        # In production, this would call the provider's batch API
        return self._batch_id

    def estimate_savings(self, total_tokens: int, model: str) -> dict[str, Any]:
        """Estimate cost savings from batching."""
        # Rough pricing
        pricing = {
            "gpt-4o": 0.0025 / 1000,
            "gpt-4o-mini": 0.00015 / 1000,
            "claude-sonnet-4-20250514": 0.003 / 1000,
            "claude-3-haiku": 0.00025 / 1000,
        }

        price_per_token = pricing.get(model, 0.002 / 1000)
        regular_cost = total_tokens * price_per_token
        batch_cost = regular_cost * (1 - self.config.batch_discount)
        savings = regular_cost - batch_cost

        return {
            "regular_cost": f"${regular_cost:.4f}",
            "batch_cost": f"${batch_cost:.4f}",
            "savings": f"${savings:.4f}",
            "savings_percent": f"{self.config.batch_discount * 100:.0f}%",
        }
