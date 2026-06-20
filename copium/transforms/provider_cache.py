"""Provider-Cache Composition.

Explicitly compose with provider caching: mark stable prefixes with
cache_control, compress the variable suffix. Both savings stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from copium.config import CopiumConfig
from copium.tokenizer import Tokenizer

from .base import Transform, TransformResult


@dataclass
class ProviderCacheConfig:
    """Configuration for provider-cache composition."""

    enabled: bool = False

    # Provider cache breakpoints
    # Anthropic: cache_control = {"type": "ephemeral"}
    # OpenAI: no explicit cache control (implicit prefix caching)
    provider: str = "anthropic"  # "anthropic" or "openai"

    # How many messages to mark as cacheable (from the start)
    cacheable_message_count: int = 3  # System + first user + first assistant

    # Minimum tokens in prefix to bother caching
    min_cacheable_tokens: int = 1024

    # Insert cache breakpoints every N messages
    breakpoint_interval: int = 5


class ProviderCacheComposition(Transform):
    """Mark stable prefixes for provider caching while compressing the rest.

    This transform composes two savings mechanisms:
    1. Provider prefix caching (90% discount on cached tokens)
    2. Copium compression (50-80% reduction on variable content)

    The stable prefix (system prompt, early conversation) is marked
    for caching, while the variable suffix is compressed.
    """

    name = "provider_cache_composition"

    def __init__(self, config: ProviderCacheConfig | None = None) -> None:
        self.config = config or ProviderCacheConfig()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _add_cache_breakpoints(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add cache_control breakpoints to messages for Anthropic."""
        if self.config.provider != "anthropic":
            return messages

        result = []
        for i, msg in enumerate(messages):
            new_msg = dict(msg)

            # Add cache breakpoint at strategic points
            if i < self.config.cacheable_message_count:
                # Mark early messages as cacheable
                new_msg["cache_control"] = {"type": "ephemeral"}
            elif i % self.config.breakpoint_interval == 0 and i > 0:
                # Add periodic breakpoints
                new_msg["cache_control"] = {"type": "ephemeral"}

            result.append(new_msg)

        return result

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Add provider cache breakpoints to messages."""
        if not self.enabled:
            return TransformResult(
                messages=messages,
                tokens_before=0,
                tokens_after=0,
                transforms_applied=[],
            )

        tokens_before = tokenizer.count_messages(messages)

        # Add cache breakpoints
        result_messages = self._add_cache_breakpoints(messages)

        tokens_after = tokenizer.count_messages(result_messages)

        # This transform doesn't reduce tokens - it enables provider caching
        # The savings come from the provider's cache discount
        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=[self.name] if self.config.provider == "anthropic" else [],
        )


@dataclass
class CacheCompositionResult:
    """Result of cache composition analysis."""

    cacheable_tokens: int = 0
    compressible_tokens: int = 0
    estimated_cache_hit_rate: float = 0.0
    estimated_provider_savings: float = 0.0
    estimated_compression_savings: float = 0.0
    total_estimated_savings: float = 0.0


def analyze_cache_composition(
    messages: list[dict[str, Any]],
    tokenizer: Tokenizer,
    config: ProviderCacheConfig | None = None,
) -> CacheCompositionResult:
    """Analyze how much can be cached vs compressed.

    Returns breakdown of cacheable vs compressible tokens.
    """
    config = config or ProviderCacheConfig()
    result = CacheCompositionResult()

    total_tokens = tokenizer.count_messages(messages)

    # First N messages are cacheable
    cacheable_messages = messages[: config.cacheable_message_count]
    result.cacheable_tokens = tokenizer.count_messages(cacheable_messages)

    # Rest is compressible
    result.compressible_tokens = total_tokens - result.cacheable_tokens

    # Estimate savings
    # Anthropic: 90% discount on cache hits
    if config.provider == "anthropic":
        result.estimated_cache_hit_rate = 0.8  # 80% hit rate after warmup
        result.estimated_provider_savings = (
            result.cacheable_tokens * 0.9 * result.estimated_cache_hit_rate
        )

    # Compression savings on compressible portion
    result.estimated_compression_savings = result.compressible_tokens * 0.5  # 50% compression

    result.total_estimated_savings = (
        result.estimated_provider_savings + result.estimated_compression_savings
    )

    return result
