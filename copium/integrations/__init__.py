"""Copium integrations with popular LLM frameworks.

Available integrations:

LangChain (pip install copium[langchain]):
    - CopiumChatModel: Drop-in wrapper for any LangChain chat model
    - CopiumChatMessageHistory: Automatic conversation compression
    - CopiumDocumentCompressor: Relevance-based document filtering
    - CopiumToolWrapper: Tool output compression for agents
    - StreamingMetricsTracker: Token counting during streaming
    - CopiumLangSmithCallbackHandler: LangSmith trace enrichment

Agno (pip install agno):
    - CopiumAgnoModel: Drop-in wrapper for any Agno model
    - CopiumPreHook/CopiumPostHook: Agent-level hooks for tracking
    - create_copium_hooks: Convenience function to create hook pairs

MCP (Model Context Protocol):
    - CopiumMCPCompressor: Compress MCP tool results
    - compress_tool_result: Simple function for tool compression

Example:
    # LangChain integration
    from copium.integrations import CopiumChatModel
    # or explicitly:
    from copium.integrations.langchain import CopiumChatModel

    # Agno integration
    from copium.integrations.agno import CopiumAgnoModel
    # or explicitly:
    from copium.integrations.agno import CopiumAgnoModel

    # MCP integration
    from copium.integrations import compress_tool_result
    # or explicitly:
    from copium.integrations.mcp import compress_tool_result
"""

# Re-export from langchain subpackage for backwards compatibility
from .langchain import (
    # Retrievers
    CompressionMetrics,
    # Core
    CopiumCallbackHandler,
    # Memory
    CopiumChatMessageHistory,
    CopiumChatModel,
    CopiumDocumentCompressor,
    # LangSmith
    CopiumLangSmithCallbackHandler,
    CopiumRunnable,
    # Agents
    CopiumToolWrapper,
    OptimizationMetrics,
    # Streaming
    StreamingMetrics,
    StreamingMetricsCallback,
    StreamingMetricsTracker,
    ToolCompressionMetrics,
    ToolMetricsCollector,
    # Provider Detection
    detect_provider,
    get_copium_provider,
    get_model_name_from_langchain,
    get_tool_metrics,
    is_langsmith_available,
    is_langsmith_tracing_enabled,
    langchain_available,
    optimize_messages,
    reset_tool_metrics,
    track_async_streaming_response,
    track_streaming_response,
    wrap_tools_with_copium,
)

# Re-export from mcp subpackage for backwards compatibility
from .mcp import (
    DEFAULT_MCP_PROFILES,
    CopiumMCPClientWrapper,
    CopiumMCPCompressor,
    MCPCompressionResult,
    MCPToolProfile,
    compress_tool_result,
    compress_tool_result_with_metrics,
    create_copium_mcp_proxy,
)

# Re-export from agno subpackage (optional dependency)
try:
    from .agno import (
        CopiumAgnoModel,
        CopiumPostHook,
        CopiumPreHook,
        agno_available,
        create_copium_hooks,
        get_model_name_from_agno,
    )
    from .agno import OptimizationMetrics as AgnoOptimizationMetrics
    from .agno import get_copium_provider as get_agno_provider
    from .agno import optimize_messages as optimize_agno_messages

    _AGNO_AVAILABLE = True
except ImportError:
    _AGNO_AVAILABLE = False

__all__ = [
    # LangChain Core
    "CopiumChatModel",
    "CopiumCallbackHandler",
    "CopiumRunnable",
    "OptimizationMetrics",
    "optimize_messages",
    "langchain_available",
    # Provider Detection
    "detect_provider",
    "get_copium_provider",
    "get_model_name_from_langchain",
    # Memory
    "CopiumChatMessageHistory",
    # Retrievers
    "CopiumDocumentCompressor",
    "CompressionMetrics",
    # Agents
    "CopiumToolWrapper",
    "ToolCompressionMetrics",
    "ToolMetricsCollector",
    "wrap_tools_with_copium",
    "get_tool_metrics",
    "reset_tool_metrics",
    # LangSmith
    "CopiumLangSmithCallbackHandler",
    "is_langsmith_available",
    "is_langsmith_tracing_enabled",
    # Streaming
    "StreamingMetricsTracker",
    "StreamingMetricsCallback",
    "StreamingMetrics",
    "track_streaming_response",
    "track_async_streaming_response",
    # MCP
    "CopiumMCPCompressor",
    "CopiumMCPClientWrapper",
    "MCPCompressionResult",
    "MCPToolProfile",
    "compress_tool_result",
    "compress_tool_result_with_metrics",
    "create_copium_mcp_proxy",
    "DEFAULT_MCP_PROFILES",
    # Agno
    "CopiumAgnoModel",
    "CopiumPreHook",
    "CopiumPostHook",
    "agno_available",
    "create_copium_hooks",
    "get_agno_provider",
    "get_model_name_from_agno",
    "AgnoOptimizationMetrics",
    "optimize_agno_messages",
    # Local Model Integrations
    "detect_local_backends",
    "OllamaIntegration",
    "LlamaCppIntegration",
    "LMStudioIntegration",
    "LocalTriageEngine",
]

# Re-export from local subpackage (local model integrations)
from .local import (
    LlamaCppIntegration,
    LMStudioIntegration,
    LocalTriageEngine,
    OllamaIntegration,
    detect_local_backends,
)
