"""Session archive management for AI coding agents.

Provides compression, search, and cross-agent context sharing for
session archives from Claude Code, Cursor, Aider, OpenCode, and more.
"""

from __future__ import annotations

from .archive import CompactConfig, CompactResult, SessionArchive, SessionMessage
from .compactor import SessionCompactor
from .applicator import SessionApplicator
from .expander import SessionExpander
from .search import SearchConfig, SearchResult, SessionSearch

__all__ = [
    "CompactConfig",
    "CompactResult",
    "SearchConfig",
    "SearchResult",
    "SessionApplicator",
    "SessionArchive",
    "SessionCompactor",
    "SessionExpander",
    "SessionMessage",
    "SessionSearch",
]
