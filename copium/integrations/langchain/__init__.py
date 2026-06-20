"""LangChain integration for Copium.

This package provides seamless integration with LangChain, including:
- CopiumChatModel: Drop-in wrapper for any LangChain chat model
- CopiumChatMessageHistory: Automatic conversation compression
- CopiumDocumentCompressor: Relevance-based document filtering
- CopiumToolWrapper: Tool output compression for agents
- StreamingMetricsTracker: Token counting during streaming
- CopiumLangSmithCallbackHandler: LangSmith trace enrichment
- compress_tool_messages: LangGraph pre-model hook for ToolMessage compression
- create_compress_tool_messages_node: LangGraph node factory

Example:
    from langchain_openai import ChatOpenAI
    from copium.integrations.langchain import CopiumChatModel

    # Wrap any LangChain model
    llm = CopiumChatModel(ChatOpenAI(model="gpt-4o"))

    # Use like normal - optimization happens automatically
    response = llm.invoke("Hello!")

Install: pip install copium[langchain]
"""

# Agent tool wrapping
from .agents import (
    CopiumToolWrapper,
    ToolCompressionMetrics,
    ToolMetricsCollector,
    get_tool_metrics,
    reset_tool_metrics,
    wrap_tools_with_copium,
)

# Core chat model wrapper
from .chat_model import (
    CopiumCallbackHandler,
    CopiumChatModel,
    CopiumRunnable,
    OptimizationMetrics,
    langchain_available,
    optimize_messages,
)

# LangGraph integration
from .langgraph import (
    CompressToolMessagesConfig,
    CompressToolMessagesResult,
    ToolMessageCompressionMetrics,
    compress_tool_messages,
    create_compress_tool_messages_node,
)

# LangSmith integration
from .langsmith import (
    CopiumLangSmithCallbackHandler,
    is_langsmith_available,
    is_langsmith_tracing_enabled,
)

# Memory integration
from .memory import CopiumChatMessageHistory

# Provider auto-detection
from .providers import (
    detect_provider,
    get_copium_provider,
    get_model_name_from_langchain,
)

# Retriever integration
from .retriever import CompressionMetrics, CopiumDocumentCompressor

# Streaming metrics
from .streaming import (
    StreamingMetrics,
    StreamingMetricsCallback,
    StreamingMetricsTracker,
    track_async_streaming_response,
    track_streaming_response,
)

__all__ = [
    # Core
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
    # LangGraph
    "compress_tool_messages",
    "create_compress_tool_messages_node",
    "CompressToolMessagesConfig",
    "CompressToolMessagesResult",
    "ToolMessageCompressionMetrics",
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
]
