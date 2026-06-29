"""Agent context management package.

Provides automatic context window management, session persistence,
compressed memory, and tool result caching for AI agent workflows.

This goes beyond ContextCrumb's compression-only approach by managing
the full agent context lifecycle: compress, cache, persist, restore.
"""

from copium.agent.context_manager import AgentContextManager
from copium.agent.memory import CompressedMemoryStore, MemoryEntry, MemoryPriority
from copium.agent.session import SessionStore, CompressedSession
from copium.agent.tool_cache import SemanticToolCache

__all__ = [
    "AgentContextManager",
    "CompressedMemoryStore",
    "CompressedSession",
    "MemoryEntry",
    "MemoryPriority",
    "SessionStore",
    "SemanticToolCache",
]
