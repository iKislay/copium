"""
Copium - The Context Optimization Layer for LLM Applications.

Cut your LLM costs by 50-90% without losing accuracy.

Copium wraps LLM clients to provide:
- Smart compression of tool outputs (keeps errors, anomalies, relevant items)
- Cache-aligned prefix optimization for better provider cache hits
- Rolling window token management for long conversations
- Full streaming support with zero accuracy loss

Quick Start:

    from copium import CopiumClient, OpenAIProvider
    from openai import OpenAI

    # Wrap your existing client
    client = CopiumClient(
        original_client=OpenAI(),
        provider=OpenAIProvider(),
        default_mode="optimize",
    )

    # Use exactly like the original client
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": "Hello!"},
        ],
    )

    # Check savings
    stats = client.get_stats()
    print(f"Tokens saved: {stats['session']['tokens_saved_total']}")

Verify It's Working:

    # Validate configuration
    result = client.validate_setup()
    if not result["valid"]:
        print("Issues:", result)

    # Enable logging to see what's happening
    import logging
    logging.basicConfig(level=logging.INFO)
    # INFO:copium.transforms.pipeline:Pipeline complete: 45000 -> 4500 tokens

Simulate Before Sending:

    plan = client.chat.completions.simulate(
        model="gpt-4o",
        messages=large_messages,
    )
    print(f"Would save {plan.tokens_saved} tokens")
    print(f"Transforms: {plan.transforms}")

Error Handling:

    from copium import CopiumError, ConfigurationError, ProviderError

    try:
        response = client.chat.completions.create(...)
    except ConfigurationError as e:
        print(f"Config issue: {e.details}")
    except CopiumError as e:
        print(f"Copium error: {e}")

For more examples, see https://github.com/copium-sdk/copium/tree/main/examples
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ._version import __version__  # noqa: F401
from .compress import CompressConfig, CompressResult, compress, compress_spreadsheet

# Keep a real callable bound for the one-function compression API so
# `from copium import compress` is never shadowed by the submodule object.

__all__ = [
    # Main client
    "CopiumClient",
    # Providers
    "Provider",
    "TokenCounter",
    "OpenAIProvider",
    "AnthropicProvider",
    # Exceptions
    "CopiumError",
    "ConfigurationError",
    "ProviderError",
    "StorageError",
    "CompressionError",
    "TokenizationError",
    "CacheError",
    "ValidationError",
    "TransformError",
    # Config
    "CopiumConfig",
    "CopiumMode",
    "SmartCrusherConfig",
    "CacheAlignerConfig",
    "CacheOptimizerConfig",
    "RelevanceScorerConfig",
    # Data models
    "Block",
    "CachePrefixMetrics",
    "DiffArtifact",
    "RequestMetrics",
    "SimulationResult",
    "TransformDiff",
    "TransformResult",
    "WasteSignals",
    # Transforms
    "SmartCrusher",
    "CacheAligner",
    "TransformPipeline",
    # Cache optimizers
    "BaseCacheOptimizer",
    "CacheConfig",
    "CacheMetrics",
    "CacheResult",
    "CacheStrategy",
    "OptimizationContext",
    "CacheOptimizerRegistry",
    "AnthropicCacheOptimizer",
    "OpenAICacheOptimizer",
    "GoogleCacheOptimizer",
    "SemanticCache",
    "SemanticCacheLayer",
    # Relevance scoring - BM25 always available, embeddings require sentence-transformers
    "RelevanceScore",
    "RelevanceScorer",
    "BM25Scorer",
    "EmbeddingScorer",
    "HybridScorer",
    "create_scorer",
    "embedding_available",
    # Utilities
    "Tokenizer",
    "count_tokens_text",
    "count_tokens_messages",
    "generate_report",
    # Observability
    "CopiumOtelMetrics",
    "CopiumTracer",
    "LangfuseTracingConfig",
    "OTelMetricsConfig",
    "configure_otel_metrics",
    "configure_langfuse_tracing",
    "get_copium_tracer",
    "get_langfuse_tracing_status",
    "get_otel_metrics",
    "get_otel_metrics_status",
    "reset_copium_tracing",
    "reset_otel_metrics",
    # Memory - optional hierarchical memory system
    "with_memory",  # Main user-facing API
    "Memory",
    "ScopeLevel",
    "HierarchicalMemory",
    "MemoryConfig",
    "EmbedderBackend",
    # One-function compression API
    "compress",
    "compress_spreadsheet",
    "CompressConfig",
    "CompressResult",
    # Hooks
    "CompressionHooks",
    "CompressContext",
    "CompressEvent",
    # Canonical pipeline
    "PipelineStage",
    "PipelineEvent",
    "PipelineExtensionManager",
    "CANONICAL_PIPELINE_STAGES",
    # Shared context for multi-agent workflows
    "SharedContext",
    # Session management
    "SessionArchive",
    "SessionCompactor",
    "SessionSearch",
]

# Keep package-level imports lightweight so `import copium` does not eagerly
# load provider SDKs, ML stacks, or optional proxy/runtime integrations.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Main client
    "CopiumClient": ("copium.client", "CopiumClient"),
    # Providers
    "Provider": ("copium.providers", "Provider"),
    "TokenCounter": ("copium.providers", "TokenCounter"),
    "OpenAIProvider": ("copium.providers", "OpenAIProvider"),
    "AnthropicProvider": ("copium.providers", "AnthropicProvider"),
    # Exceptions
    "CopiumError": ("copium.exceptions", "CopiumError"),
    "ConfigurationError": ("copium.exceptions", "ConfigurationError"),
    "ProviderError": ("copium.exceptions", "ProviderError"),
    "StorageError": ("copium.exceptions", "StorageError"),
    "CompressionError": ("copium.exceptions", "CompressionError"),
    "TokenizationError": ("copium.exceptions", "TokenizationError"),
    "CacheError": ("copium.exceptions", "CacheError"),
    "ValidationError": ("copium.exceptions", "ValidationError"),
    "TransformError": ("copium.exceptions", "TransformError"),
    # Config
    "CopiumConfig": ("copium.config", "CopiumConfig"),
    "CopiumMode": ("copium.config", "CopiumMode"),
    "SmartCrusherConfig": ("copium.config", "SmartCrusherConfig"),
    "CacheAlignerConfig": ("copium.config", "CacheAlignerConfig"),
    "CacheOptimizerConfig": ("copium.config", "CacheOptimizerConfig"),
    "RelevanceScorerConfig": ("copium.config", "RelevanceScorerConfig"),
    # Data models
    "Block": ("copium.config", "Block"),
    "CachePrefixMetrics": ("copium.config", "CachePrefixMetrics"),
    "DiffArtifact": ("copium.config", "DiffArtifact"),
    "RequestMetrics": ("copium.config", "RequestMetrics"),
    "SimulationResult": ("copium.config", "SimulationResult"),
    "TransformDiff": ("copium.config", "TransformDiff"),
    "TransformResult": ("copium.config", "TransformResult"),
    "WasteSignals": ("copium.config", "WasteSignals"),
    # Transforms
    "SmartCrusher": ("copium.transforms", "SmartCrusher"),
    "CacheAligner": ("copium.transforms", "CacheAligner"),
    "TransformPipeline": ("copium.transforms", "TransformPipeline"),
    # Cache optimizers
    "BaseCacheOptimizer": ("copium.cache", "BaseCacheOptimizer"),
    "CacheConfig": ("copium.cache", "CacheConfig"),
    "CacheMetrics": ("copium.cache", "CacheMetrics"),
    "CacheResult": ("copium.cache", "CacheResult"),
    "CacheStrategy": ("copium.cache", "CacheStrategy"),
    "OptimizationContext": ("copium.cache", "OptimizationContext"),
    "CacheOptimizerRegistry": ("copium.cache", "CacheOptimizerRegistry"),
    "AnthropicCacheOptimizer": ("copium.cache", "AnthropicCacheOptimizer"),
    "OpenAICacheOptimizer": ("copium.cache", "OpenAICacheOptimizer"),
    "GoogleCacheOptimizer": ("copium.cache", "GoogleCacheOptimizer"),
    "SemanticCache": ("copium.cache", "SemanticCache"),
    "SemanticCacheLayer": ("copium.cache", "SemanticCacheLayer"),
    # Relevance scoring
    "RelevanceScore": ("copium.relevance", "RelevanceScore"),
    "RelevanceScorer": ("copium.relevance", "RelevanceScorer"),
    "BM25Scorer": ("copium.relevance", "BM25Scorer"),
    "EmbeddingScorer": ("copium.relevance", "EmbeddingScorer"),
    "HybridScorer": ("copium.relevance", "HybridScorer"),
    "create_scorer": ("copium.relevance", "create_scorer"),
    "embedding_available": ("copium.relevance", "embedding_available"),
    # Utilities
    "Tokenizer": ("copium.tokenizer", "Tokenizer"),
    "count_tokens_text": ("copium.tokenizer", "count_tokens_text"),
    "count_tokens_messages": ("copium.tokenizer", "count_tokens_messages"),
    "generate_report": ("copium.reporting", "generate_report"),
    # Observability
    "CopiumOtelMetrics": ("copium.observability", "CopiumOtelMetrics"),
    "CopiumTracer": ("copium.observability", "CopiumTracer"),
    "LangfuseTracingConfig": ("copium.observability", "LangfuseTracingConfig"),
    "OTelMetricsConfig": ("copium.observability", "OTelMetricsConfig"),
    "configure_otel_metrics": ("copium.observability", "configure_otel_metrics"),
    "configure_langfuse_tracing": ("copium.observability", "configure_langfuse_tracing"),
    "get_copium_tracer": ("copium.observability", "get_copium_tracer"),
    "get_langfuse_tracing_status": ("copium.observability", "get_langfuse_tracing_status"),
    "get_otel_metrics": ("copium.observability", "get_otel_metrics"),
    "get_otel_metrics_status": ("copium.observability", "get_otel_metrics_status"),
    "reset_copium_tracing": ("copium.observability", "reset_copium_tracing"),
    "reset_otel_metrics": ("copium.observability", "reset_otel_metrics"),
    # One-function API
    "compress": ("copium.compress", "compress"),
    "compress_spreadsheet": ("copium.compress", "compress_spreadsheet"),
    # Hooks
    "CompressionHooks": ("copium.hooks", "CompressionHooks"),
    "CompressContext": ("copium.hooks", "CompressContext"),
    "CompressEvent": ("copium.hooks", "CompressEvent"),
    # Canonical pipeline
    "PipelineStage": ("copium.pipeline", "PipelineStage"),
    "PipelineEvent": ("copium.pipeline", "PipelineEvent"),
    "PipelineExtensionManager": ("copium.pipeline", "PipelineExtensionManager"),
    "CANONICAL_PIPELINE_STAGES": ("copium.pipeline", "CANONICAL_PIPELINE_STAGES"),
    # Shared context
    "SharedContext": ("copium.shared_context", "SharedContext"),
    # Session management
    "SessionArchive": ("copium.session", "SessionArchive"),
    "SessionCompactor": ("copium.session", "SessionCompactor"),
    "SessionSearch": ("copium.session", "SessionSearch"),
}

# Memory remains optional and preserves the long-standing behavior of exposing
# `None` when the extra dependencies are not installed.
_OPTIONAL_EXPORTS = {
    "with_memory": ("copium.memory", "with_memory"),
    "Memory": ("copium.memory", "Memory"),
    "ScopeLevel": ("copium.memory", "ScopeLevel"),
    "HierarchicalMemory": ("copium.memory", "HierarchicalMemory"),
    "MemoryConfig": ("copium.memory", "MemoryConfig"),
    "EmbedderBackend": ("copium.memory", "EmbedderBackend"),
}


def __getattr__(name: str) -> Any:
    """Resolve package exports lazily while preserving legacy import paths."""
    module_attr = _LAZY_EXPORTS.get(name)
    if module_attr is not None:
        module_name, attr_name = module_attr
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value

    optional_module_attr = _OPTIONAL_EXPORTS.get(name)
    if optional_module_attr is not None:
        module_name, attr_name = optional_module_attr
        try:
            value = getattr(import_module(module_name), attr_name)
        except ImportError:
            value = None
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
