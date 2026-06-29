"""Session archive management for AI coding agents.

Provides compression, search, and cross-agent context sharing for
session archives from Claude Code, Cursor, Aider, OpenCode, and more.

Usage::

    from copium.session import SessionArchive, SessionCompactor

    archive = SessionArchive(Path("session.jsonl"))
    compactor = SessionCompactor()
    compacted, result = compactor.compact(archive)
    print(f"Savings: {result.savings_pct:.1f}%")
"""

from __future__ import annotations

from .archive import CompactConfig, CompactResult, SessionArchive, SessionMessage
from .compactor import SessionCompactor
from .applicator import SessionApplicator
from .expander import CCRStoreBridge, SessionExpander
from .search import SearchConfig, SearchResult, SessionSearch

__all__ = [
    "CCRStoreBridge",
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
