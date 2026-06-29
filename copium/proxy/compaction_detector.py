"""Compaction detector — detect when auto-compaction is imminent.

Monitors token usage in proxy requests and triggers pre-compaction hooks
when the conversation approaches the provider's compaction threshold.

Claude Code triggers auto-compaction at ~83.5% of the context window.
This module detects that threshold and saves session state before
the provider compacts (and loses granular context).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default compaction thresholds by provider
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "anthropic": 0.835,
    "openai": 0.80,
    "google": 0.80,
}

# Context windows by model (tokens)
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
}


@dataclass
class CompactionEvent:
    """Record of a detected compaction approach."""

    session_id: str
    model: str
    token_usage: int
    context_window: int
    threshold: float
    usage_pct: float
    timestamp: float = field(default_factory=time.time)
    checkpoint_saved: bool = False

    @property
    def tokens_remaining(self) -> int:
        return self.context_window - self.token_usage


@dataclass
class DetectorConfig:
    """Configuration for compaction detection."""

    # Trigger when usage exceeds this fraction of context window
    threshold_override: float | None = None
    # Provider name for default threshold lookup
    provider: str = "anthropic"
    # Enable/disable detection
    enabled: bool = True
    # Cooldown between events for same session (seconds)
    cooldown_seconds: float = 60.0
    # Minimum tokens to trigger (avoid spurious triggers on small sessions)
    min_tokens_for_trigger: int = 50_000


class CompactionDetector:
    """Detect when a session is approaching auto-compaction threshold.

    Monitors input token counts on requests passing through the proxy.
    When a session crosses the configured threshold, emits a CompactionEvent
    that pre-compaction hooks can act on.
    """

    def __init__(self, config: DetectorConfig | None = None):
        self.config = config or DetectorConfig()
        self._last_event_time: dict[str, float] = {}
        self._events: list[CompactionEvent] = []

    @property
    def events(self) -> list[CompactionEvent]:
        """All detected compaction approach events."""
        return list(self._events)

    def get_threshold(self, model: str | None = None) -> float:
        """Get the compaction threshold for a model/provider."""
        if self.config.threshold_override is not None:
            return self.config.threshold_override
        return _DEFAULT_THRESHOLDS.get(self.config.provider, 0.80)

    def get_context_window(self, model: str) -> int:
        """Get context window size for a model."""
        # Try exact match first
        if model in _CONTEXT_WINDOWS:
            return _CONTEXT_WINDOWS[model]
        # Try prefix match
        for key, window in _CONTEXT_WINDOWS.items():
            if model.startswith(key):
                return window
        # Default to 200K for unknown models
        return 200_000

    def check(
        self,
        session_id: str,
        model: str,
        input_tokens: int,
        messages: list[dict[str, Any]] | None = None,
    ) -> CompactionEvent | None:
        """Check if a request is approaching the compaction threshold.

        Args:
            session_id: Unique session identifier.
            model: Model name being used.
            input_tokens: Token count for the current request.
            messages: Optional message list for additional analysis.

        Returns:
            CompactionEvent if threshold is crossed, None otherwise.
        """
        if not self.config.enabled:
            return None

        context_window = self.get_context_window(model)
        threshold = self.get_threshold(model)
        usage_pct = input_tokens / context_window

        # Check minimum token requirement
        if input_tokens < self.config.min_tokens_for_trigger:
            return None

        # Check if we're approaching the threshold
        if usage_pct < threshold:
            return None

        # Check cooldown
        now = time.time()
        last_time = self._last_event_time.get(session_id, 0)
        if now - last_time < self.config.cooldown_seconds:
            return None

        # Threshold crossed — create event
        event = CompactionEvent(
            session_id=session_id,
            model=model,
            token_usage=input_tokens,
            context_window=context_window,
            threshold=threshold,
            usage_pct=usage_pct,
        )

        self._last_event_time[session_id] = now
        self._events.append(event)

        logger.warning(
            "Compaction imminent for session %s: %.1f%% of %dK context used "
            "(%d tokens remaining)",
            session_id,
            usage_pct * 100,
            context_window // 1000,
            event.tokens_remaining,
        )

        return event

    def reset_session(self, session_id: str) -> None:
        """Reset tracking for a session (e.g., after compaction completes)."""
        self._last_event_time.pop(session_id, None)

    def stats(self) -> dict[str, Any]:
        """Get detector statistics."""
        return {
            "enabled": self.config.enabled,
            "provider": self.config.provider,
            "threshold": self.get_threshold(),
            "total_events": len(self._events),
            "active_sessions": len(self._last_event_time),
        }
