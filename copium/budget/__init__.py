"""Budget Enforcement + Spend Guard.

Pre-send circuit breaker: block runaway requests before they hit the provider.
Inspired by TokenPak's TIP Spend Guard pattern.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from copium.config import CopiumConfig


@dataclass
class BudgetConfig:
    """Configuration for budget enforcement."""

    enabled: bool = False

    # Per-request limits
    max_tokens_per_request: int = 100_000  # Max input tokens per request
    max_cost_per_request: float = 1.00  # Max cost per request ($)

    # Per-minute limits
    max_requests_per_minute: int = 60
    max_tokens_per_minute: int = 1_000_000
    max_cost_per_minute: float = 10.00

    # Per-hour limits
    max_requests_per_hour: int = 1000
    max_tokens_per_hour: int = 10_000_000
    max_cost_per_hour: float = 100.00

    # Per-day limits
    max_requests_per_day: int = 10_000
    max_tokens_per_day: int = 100_000_000
    max_cost_per_day: float = 1000.00

    # Hard limit: block all requests if exceeded
    hard_limit_cost_per_day: float = 5000.00

    # Pricing for cost estimation
    pricing: dict[str, float] = field(
        default_factory=lambda: {
            "gpt-4o": 0.0025 / 1000,
            "gpt-4o-mini": 0.00015 / 1000,
            "claude-sonnet-4-20250514": 0.003 / 1000,
            "claude-3-haiku": 0.00025 / 1000,
        }
    )


@dataclass
class SpendEntry:
    """A single spend entry for tracking."""

    timestamp: float
    tokens: int
    cost: float
    model: str
    request_id: str = ""


class SpendGuard:
    """Circuit breaker for API spend.

    Tracks usage and blocks requests that exceed budget limits.
    """

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig()
        self._entries: list[SpendEntry] = []
        self._blocked: bool = False
        self._block_reason: str = ""

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _cleanup_old_entries(self) -> None:
        """Remove entries older than 24 hours."""
        cutoff = time.time() - 86400  # 24 hours
        self._entries = [e for e in self._entries if e.timestamp > cutoff]

    def _get_entries_in_window(self, seconds: float) -> list[SpendEntry]:
        """Get entries within a time window."""
        cutoff = time.time() - seconds
        return [e for e in self._entries if e.timestamp > cutoff]

    def _estimate_cost(self, tokens: int, model: str) -> float:
        """Estimate cost from tokens."""
        price = self.config.pricing.get(model, 0.002 / 1000)
        return tokens * price

    def check_request(
        self,
        tokens: int,
        model: str,
        request_id: str = "",
    ) -> tuple[bool, str]:
        """Check if a request should be allowed.

        Returns (allowed, reason).
        """
        if not self.enabled:
            return True, ""

        self._cleanup_old_entries()

        cost = self._estimate_cost(tokens, model)

        # Check per-request limits
        if tokens > self.config.max_tokens_per_request:
            return False, f"Request too large: {tokens} tokens (max: {self.config.max_tokens_per_request})"

        if cost > self.config.max_cost_per_request:
            return False, f"Request too expensive: ${cost:.4f} (max: ${self.config.max_cost_per_request})"

        # Check per-minute limits
        minute_entries = self._get_entries_in_window(60)
        minute_tokens = sum(e.tokens for e in minute_entries)
        minute_cost = sum(e.cost for e in minute_entries)
        minute_requests = len(minute_entries)

        if minute_requests >= self.config.max_requests_per_minute:
            return False, f"Rate limit exceeded: {minute_requests} requests/min (max: {self.config.max_requests_per_minute})"

        if minute_tokens + tokens > self.config.max_tokens_per_minute:
            return False, f"Token limit exceeded: {minute_tokens + tokens}/min (max: {self.config.max_tokens_per_minute})"

        if minute_cost + cost > self.config.max_cost_per_minute:
            return False, f"Cost limit exceeded: ${minute_cost + cost:.4f}/min (max: ${self.config.max_cost_per_minute})"

        # Check per-hour limits
        hour_entries = self._get_entries_in_window(3600)
        hour_cost = sum(e.cost for e in hour_entries)

        if hour_cost + cost > self.config.max_cost_per_hour:
            return False, f"Hourly cost limit exceeded: ${hour_cost + cost:.4f}/hr (max: ${self.config.max_cost_per_hour})"

        # Check per-day limits
        day_entries = self._get_entries_in_window(86400)
        day_cost = sum(e.cost for e in day_entries)

        if day_cost + cost > self.config.max_cost_per_day:
            return False, f"Daily cost limit exceeded: ${day_cost + cost:.4f}/day (max: ${self.config.max_cost_per_day})"

        # Hard limit
        if day_cost + cost > self.config.hard_limit_cost_per_day:
            self._blocked = True
            self._block_reason = f"HARD LIMIT EXCEEDED: ${day_cost + cost:.4f} > ${self.config.hard_limit_cost_per_day}"
            return False, self._block_reason

        return True, ""

    def record_request(
        self,
        tokens: int,
        model: str,
        request_id: str = "",
    ) -> None:
        """Record a completed request for tracking."""
        cost = self._estimate_cost(tokens, model)

        self._entries.append(SpendEntry(
            timestamp=time.time(),
            tokens=tokens,
            cost=cost,
            model=model,
            request_id=request_id,
        ))

    def get_usage_stats(self) -> dict[str, Any]:
        """Get current usage statistics."""
        self._cleanup_old_entries()

        minute_entries = self._get_entries_in_window(60)
        hour_entries = self._get_entries_in_window(3600)
        day_entries = self._get_entries_in_window(86400)

        return {
            "blocked": self._blocked,
            "block_reason": self._block_reason,
            "minute": {
                "requests": len(minute_entries),
                "tokens": sum(e.tokens for e in minute_entries),
                "cost": sum(e.cost for e in minute_entries),
            },
            "hour": {
                "requests": len(hour_entries),
                "tokens": sum(e.tokens for e in hour_entries),
                "cost": sum(e.cost for e in hour_entries),
            },
            "day": {
                "requests": len(day_entries),
                "tokens": sum(e.tokens for e in day_entries),
                "cost": sum(e.cost for e in day_entries),
            },
        }

    def reset(self) -> None:
        """Reset all tracking (e.g., for a new billing period)."""
        self._entries.clear()
        self._blocked = False
        self._block_reason = ""
