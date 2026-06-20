"""Budget Enforcement + Spend Guard.

Pre-send circuit breaker: block runaway requests before they hit the provider.
Inspired by TokenPak's TIP Spend Guard pattern.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from copium.config import CopiumConfig

logger = logging.getLogger(__name__)


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


# ============================================================================
# Context Budget Manager
# ============================================================================


class BudgetZone(str, Enum):
    """Context usage zone classification."""

    SAFE = "safe"
    WARNING = "warning"
    DANGER = "danger"
    OVER = "over"


@dataclass
class ModelCapabilities:
    """Detected or configured model capabilities."""

    model_name: str
    max_context: int  # Maximum context window size
    kv_cache_type: str = "unknown"  # f16, q8_0, q4_0, unknown
    reliable_context: int = 0  # Computed reliable context limit
    architecture: str = ""  # e.g., "qwen2", "llama", "mistral"

    def __post_init__(self):
        if self.reliable_context == 0:
            self.reliable_context = self.max_context


@dataclass
class BudgetCheck:
    """Result of a context budget check."""

    estimated_tokens: int
    total_budget: int
    reserved_output: int
    available_for_input: int
    usage_pct: float
    zone: BudgetZone
    suggestion: str
    model: ModelCapabilities | None = None

    @property
    def fits(self) -> bool:
        return self.estimated_tokens <= self.available_for_input


@dataclass
class BudgetAllocation:
    """Detailed token budget allocation for a request."""

    total_context: int
    system_prompt_tokens: int
    reserved_output: int
    available_for_tools: int
    used_by_tools: int
    remaining: int
    utilization_pct: float


# Known model context limits (common local + cloud models)
_KNOWN_MODELS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o3": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-haiku": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "qwen2.5-coder:32b": 32_768,
    "qwen2.5-coder:14b": 32_768,
    "qwen2.5-coder:7b": 32_768,
    "qwen2.5:32b": 32_768,
    "qwen2.5:14b": 32_768,
    "qwen2.5:7b": 32_768,
    "qwen3:30b": 32_768,
    "qwen3:8b": 32_768,
    "llama3.1:8b": 131_072,
    "llama3.1:70b": 131_072,
    "llama3.2:3b": 131_072,
    "gemma2:9b": 8_192,
    "gemma2:27b": 8_192,
    "codellama:34b": 16_384,
    "codellama:70b": 16_384,
    "mistral:7b": 32_768,
    "mixtral:8x7b": 32_768,
    "deepseek-coder:33b": 16_384,
    "deepseek-r1:32b": 65_536,
}

_KV_RELIABLE_FRACTIONS: dict[str, float] = {
    "f16": 0.95,
    "fp16": 0.95,
    "q8_0": 0.50,
    "q8": 0.50,
    "q4_0": 0.25,
    "q4": 0.25,
    "q4_k_m": 0.25,
    "q4_k_s": 0.25,
    "q5_k_m": 0.35,
    "q5_k_s": 0.35,
    "iq4_xs": 0.25,
    "unknown": 0.50,
}


def _normalize_model_name(model: str) -> str:
    """Normalize model name for lookup."""
    name = model.lower()
    for prefix in ("openai/", "anthropic/", "google/", "ollama/", "bedrock/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Iteratively strip suffixes (e.g., "-instruct-gguf" -> strip both)
    changed = True
    while changed:
        changed = False
        for suffix in ("-chat", "-instruct", "-gguf", "-awq", "-gptq", "-exl2"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                changed = True
    return name


def _estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from text (~4 chars per token for English)."""
    return max(1, len(text) // 4)


def _estimate_tokens_from_messages(messages: list[dict[str, Any]]) -> int:
    """Estimate total token count from a message list."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += _estimate_tokens_from_text(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += _estimate_tokens_from_text(part.get("text", ""))
                    elif part.get("type") == "tool_result":
                        result_content = part.get("content", "")
                        if isinstance(result_content, str):
                            total += _estimate_tokens_from_text(result_content)
                    elif part.get("type") == "image":
                        total += 1000
        total += 4  # Overhead for message formatting
    return total


class ContextBudgetManager:
    """Context window budget manager.

    Detects model capabilities, estimates token usage, and provides
    budget allocations that prevent context overflow and quality
    degradation on local and cloud LLMs.
    """

    def __init__(self, config: Any | None = None):
        from copium.config import ContextBudgetConfig
        self.config = config or ContextBudgetConfig()
        self._model_cache: dict[str, ModelCapabilities] = {}

    def detect_model(
        self,
        model_name: str,
        backend_url: str | None = None,
        max_context: int | None = None,
        kv_cache_type: str | None = None,
    ) -> ModelCapabilities:
        """Detect or configure model capabilities."""
        normalized = _normalize_model_name(model_name)

        if normalized in self._model_cache:
            cached = self._model_cache[normalized]
            if max_context is not None:
                cached.max_context = max_context
                cached.reliable_context = self._compute_reliable_context(
                    max_context, cached.kv_cache_type
                )
            if kv_cache_type is not None:
                cached.kv_cache_type = kv_cache_type
                cached.reliable_context = self._compute_reliable_context(
                    cached.max_context, kv_cache_type
                )
            return cached

        ctx = max_context
        if ctx is None:
            ctx = self.config.model_overrides.get(model_name)
            if ctx is None:
                ctx = self.config.model_overrides.get(normalized)
            if ctx is None:
                ctx = _KNOWN_MODELS.get(model_name) or _KNOWN_MODELS.get(normalized)
            if ctx is None:
                ctx = 32_768

        kv_type = kv_cache_type or "unknown"
        reliable = self._compute_reliable_context(ctx, kv_type)

        caps = ModelCapabilities(
            model_name=model_name,
            max_context=ctx,
            kv_cache_type=kv_type,
            reliable_context=reliable,
        )
        self._model_cache[normalized] = caps
        return caps

    def _compute_reliable_context(self, max_context: int, kv_cache_type: str) -> int:
        fraction = self.config.kv_reliable_fractions.get(
            kv_cache_type,
            _KV_RELIABLE_FRACTIONS.get(kv_cache_type, 0.50),
        )
        return int(max_context * fraction)

    def check_budget(
        self,
        messages: list[dict[str, Any]],
        model: ModelCapabilities,
        system_prompt_tokens: int = 0,
    ) -> BudgetCheck:
        """Check if messages fit within the context budget."""
        total_budget = model.reliable_context
        reserved_output = min(
            self.config.max_output_tokens,
            int(total_budget * self.config.reserve_output_pct),
        )
        available = total_budget - reserved_output - system_prompt_tokens

        estimated = _estimate_tokens_from_messages(messages)
        usage_pct = (estimated / available * 100) if available > 0 else 100.0

        if usage_pct <= self.config.warning_threshold * 100:
            zone = BudgetZone.SAFE
            suggestion = "none"
        elif usage_pct <= self.config.danger_threshold * 100:
            zone = BudgetZone.WARNING
            suggestion = "Consider compressing tool outputs or reducing context"
        elif usage_pct <= 100:
            zone = BudgetZone.DANGER
            suggestion = "Context near degradation zone. Enable session_dedup or reduce tool outputs"
        else:
            zone = BudgetZone.OVER
            suggestion = (
                f"Context overflow: {estimated} tokens > {available} available. "
                "Enable aggressive compression or reduce context"
            )

        return BudgetCheck(
            estimated_tokens=estimated,
            total_budget=total_budget,
            reserved_output=reserved_output,
            available_for_input=available,
            usage_pct=usage_pct,
            zone=zone,
            suggestion=suggestion,
            model=model,
        )

    def allocate(
        self,
        messages: list[dict[str, Any]],
        model: ModelCapabilities,
    ) -> BudgetAllocation:
        """Create a detailed token budget allocation."""
        total = model.max_context
        reserved_output = min(
            self.config.max_output_tokens,
            int(total * self.config.reserve_output_pct),
        )

        system_tokens = 0
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_tokens += _estimate_tokens_from_text(content)

        available = total - reserved_output - system_tokens
        used = _estimate_tokens_from_messages(
            [m for m in messages if m.get("role") != "system"]
        )
        remaining = max(0, available - used)

        return BudgetAllocation(
            total_context=total,
            system_prompt_tokens=system_tokens,
            reserved_output=reserved_output,
            available_for_tools=available,
            used_by_tools=used,
            remaining=remaining,
            utilization_pct=(used / available * 100) if available > 0 else 100.0,
        )

    def suggest_compression_profile(self, check: BudgetCheck) -> str:
        """Suggest a compression profile based on budget check."""
        if check.zone == BudgetZone.SAFE:
            return "moderate"
        elif check.zone == BudgetZone.WARNING:
            return "aggressive"
        else:
            return "aggressive"

    def format_report(self, check: BudgetCheck) -> str:
        """Format a human-readable budget report."""
        zone_colors = {
            BudgetZone.SAFE: "green",
            BudgetZone.WARNING: "yellow",
            BudgetZone.DANGER: "red",
            BudgetZone.OVER: "red bold",
        }
        color = zone_colors.get(check.zone, "white")

        lines = [
            f"Context Budget Report",
            f"  Model: {check.model.model_name if check.model else 'unknown'}",
            f"  Total budget: {check.total_budget:,} tokens",
            f"  Reserved output: {check.reserved_output:,} tokens",
            f"  Available for input: {check.available_for_input:,} tokens",
            f"  Estimated tokens: {check.estimated_tokens:,} tokens",
            f"  Usage: {check.usage_pct:.1f}%",
            f"  Zone: [{color}]{check.zone.value}[/{color}]",
        ]
        if check.suggestion != "none":
            lines.append(f"  Suggestion: {check.suggestion}")

        return "\n".join(lines)
