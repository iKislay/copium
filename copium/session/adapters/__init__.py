"""Session archive adapters for multiple AI coding agents.

Each adapter knows how to parse a specific agent's session format into
the unified SessionMessage representation, and how to write back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..archive import SessionMessage


class SessionAdapter(Protocol):
    """Protocol for agent-specific session format adapters."""

    name: str

    def detect(self, path: Path) -> bool:
        """Return True if the file is in this adapter's format."""
        ...

    def parse(self, path: Path) -> list[SessionMessage]:
        """Parse a session file into unified SessionMessage list."""
        ...

    def write(self, messages: list[SessionMessage], path: Path) -> None:
        """Write unified messages back in this adapter's format."""
        ...


_ADAPTERS: dict[str, SessionAdapter] = {}


def register_adapter(adapter: SessionAdapter) -> None:
    """Register a session adapter."""
    _ADAPTERS[adapter.name] = adapter


def get_adapter(name: str) -> SessionAdapter | None:
    """Get a registered adapter by name."""
    return _ADAPTERS.get(name)


def detect_adapter(path: Path) -> SessionAdapter | None:
    """Auto-detect which adapter handles a given file."""
    for adapter in _ADAPTERS.values():
        if adapter.detect(path):
            return adapter
    return None


def list_adapters() -> list[str]:
    """List all registered adapter names."""
    return list(_ADAPTERS.keys())


def _register_builtin_adapters() -> None:
    """Register all built-in adapters."""
    from .claude_code import ClaudeCodeAdapter
    from .cursor import CursorAdapter
    from .aider import AiderAdapter
    from .opencode import OpenCodeAdapter

    register_adapter(ClaudeCodeAdapter())
    register_adapter(CursorAdapter())
    register_adapter(AiderAdapter())
    register_adapter(OpenCodeAdapter())


# Auto-register on import
_register_builtin_adapters()

__all__ = [
    "SessionAdapter",
    "detect_adapter",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]
