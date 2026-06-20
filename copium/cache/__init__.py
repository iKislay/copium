"""Copium Cache Optimization Module.

This module provides a plugin-based architecture for cache optimization
across different LLM providers. Each provider has different caching
mechanisms and this module abstracts those differences.

Provider Caching Differences:
- Anthropic: Explicit cache_control blocks, 90% savings, 5-min TTL
- OpenAI: Automatic prefix caching, 50% savings, no user control
- Google: Separate CachedContent API, 75% savings + storage costs

Usage:
    from copium.cache import CacheOptimizerRegistry, SemanticCacheLayer

    # Get provider-specific optimizer
    optimizer = CacheOptimizerRegistry.get("anthropic")
    result = optimizer.optimize(messages, context)

    # With semantic caching layer
    semantic = SemanticCacheLayer(optimizer, similarity_threshold=0.95)
    result = semantic.process(messages, context)

    # Register custom optimizer
    CacheOptimizerRegistry.register("my-provider", MyOptimizer)
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Expose concrete types to static analysis while keeping runtime imports lazy.
    from copium.cache.anthropic import AnthropicCacheOptimizer  # noqa: F401
    from copium.cache.base import (  # noqa: F401
        BaseCacheOptimizer,
        CacheBreakpoint,
        CacheConfig,
        CacheMetrics,
        CacheOptimizer,
        CacheResult,
        CacheStrategy,
        OptimizationContext,
    )
    from copium.cache.compression_cache import CompressionCache  # noqa: F401
    from copium.cache.dynamic_detector import (  # noqa: F401
        DetectorConfig,
        DynamicCategory,
        DynamicContentDetector,
        DynamicSpan,
        detect_dynamic_content,
    )
    from copium.cache.google import GoogleCacheOptimizer  # noqa: F401
    from copium.cache.openai import OpenAICacheOptimizer  # noqa: F401
    from copium.cache.prefix_tracker import (  # noqa: F401
        FreezeStats,
        PrefixCacheTracker,
        PrefixFreezeConfig,
        SessionTrackerStore,
    )
    from copium.cache.registry import CacheOptimizerRegistry  # noqa: F401
    from copium.cache.semantic import SemanticCache, SemanticCacheLayer  # noqa: F401

__all__ = [
    # Base types
    "BaseCacheOptimizer",
    "CacheBreakpoint",
    "CacheConfig",
    "CacheMetrics",
    "CacheOptimizer",
    "CacheResult",
    "CacheStrategy",
    "OptimizationContext",
    # Dynamic content detection
    "DetectorConfig",
    "DynamicCategory",
    "DynamicContentDetector",
    "DynamicSpan",
    "detect_dynamic_content",
    # Registry
    "CacheOptimizerRegistry",
    # Provider implementations
    "AnthropicCacheOptimizer",
    "OpenAICacheOptimizer",
    "GoogleCacheOptimizer",
    # Semantic caching
    "SemanticCacheLayer",
    "SemanticCache",
    # Compression cache (token copium mode)
    "CompressionCache",
    # Prefix cache tracking
    "PrefixCacheTracker",
    "PrefixFreezeConfig",
    "FreezeStats",
    "SessionTrackerStore",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Base types
    "BaseCacheOptimizer": ("copium.cache.base", "BaseCacheOptimizer"),
    "CacheBreakpoint": ("copium.cache.base", "CacheBreakpoint"),
    "CacheConfig": ("copium.cache.base", "CacheConfig"),
    "CacheMetrics": ("copium.cache.base", "CacheMetrics"),
    "CacheOptimizer": ("copium.cache.base", "CacheOptimizer"),
    "CacheResult": ("copium.cache.base", "CacheResult"),
    "CacheStrategy": ("copium.cache.base", "CacheStrategy"),
    "OptimizationContext": ("copium.cache.base", "OptimizationContext"),
    # Dynamic content detection
    "DetectorConfig": ("copium.cache.dynamic_detector", "DetectorConfig"),
    "DynamicCategory": ("copium.cache.dynamic_detector", "DynamicCategory"),
    "DynamicContentDetector": ("copium.cache.dynamic_detector", "DynamicContentDetector"),
    "DynamicSpan": ("copium.cache.dynamic_detector", "DynamicSpan"),
    "detect_dynamic_content": ("copium.cache.dynamic_detector", "detect_dynamic_content"),
    # Registry
    "CacheOptimizerRegistry": ("copium.cache.registry", "CacheOptimizerRegistry"),
    # Provider implementations
    "AnthropicCacheOptimizer": ("copium.cache.anthropic", "AnthropicCacheOptimizer"),
    "OpenAICacheOptimizer": ("copium.cache.openai", "OpenAICacheOptimizer"),
    "GoogleCacheOptimizer": ("copium.cache.google", "GoogleCacheOptimizer"),
    # Semantic caching
    "SemanticCacheLayer": ("copium.cache.semantic", "SemanticCacheLayer"),
    "SemanticCache": ("copium.cache.semantic", "SemanticCache"),
    # Compression cache
    "CompressionCache": ("copium.cache.compression_cache", "CompressionCache"),
    # Prefix cache tracking
    "PrefixCacheTracker": ("copium.cache.prefix_tracker", "PrefixCacheTracker"),
    "PrefixFreezeConfig": ("copium.cache.prefix_tracker", "PrefixFreezeConfig"),
    "FreezeStats": ("copium.cache.prefix_tracker", "FreezeStats"),
    "SessionTrackerStore": ("copium.cache.prefix_tracker", "SessionTrackerStore"),
}


def __getattr__(name: str) -> object:
    if name == "__path__":
        raise AttributeError(name)

    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
