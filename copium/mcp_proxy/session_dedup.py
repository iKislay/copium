"""Session-level deduplication for MCP proxy.

Tracks tool definitions and call results across turns within a session.
When the same tool schemas or identical call results are sent again,
returns a compact dedup marker instead (~15 tokens vs thousands).

Achieves 95-99% savings on repeated tool definitions.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DedupEntry:
    """A cached entry in the dedup store."""

    key: str
    content_hash: str
    first_seen: float
    last_seen: float
    hit_count: int = 0
    token_count: int = 0


@dataclass
class SessionDedup:
    """Session-level deduplication engine.

    Tracks:
    - Tool definition sets (tools/list responses)
    - Individual tool call results (same tool + same args = same result)
    - Schema definitions (full schemas sent on first use only)
    """

    max_entries: int = 1000
    """Maximum dedup entries to track per session."""

    _definitions_cache: dict[str, DedupEntry] = field(default_factory=dict)
    """Cache of tool definition hashes."""

    _call_cache: dict[str, DedupEntry] = field(default_factory=dict)
    """Cache of tool call result hashes."""

    _schema_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Cache of full tool schemas by tool name."""

    _stats: dict[str, int] = field(default_factory=lambda: {
        "dedup_hits": 0,
        "dedup_misses": 0,
        "tokens_saved": 0,
    })

    def check_definitions(self, tools: list[dict[str, Any]]) -> str | None:
        """Check if a tool definition set has been seen before.

        Args:
            tools: List of tool definitions from tools/list.

        Returns:
            Dedup marker string if already seen, None if new.
        """
        content_hash = self._hash_tools(tools)

        if content_hash in self._definitions_cache:
            entry = self._definitions_cache[content_hash]
            entry.hit_count += 1
            entry.last_seen = time.time()
            self._stats["dedup_hits"] += 1
            self._stats["tokens_saved"] += entry.token_count
            return (
                f"[{len(tools)} tools cached, hash={content_hash[:8]}, "
                f"use copium_find_tool to discover]"
            )

        # Store new definition set
        token_estimate = sum(
            self._estimate_tokens(str(t)) for t in tools
        )
        self._definitions_cache[content_hash] = DedupEntry(
            key=content_hash,
            content_hash=content_hash,
            first_seen=time.time(),
            last_seen=time.time(),
            token_count=token_estimate,
        )
        self._stats["dedup_misses"] += 1
        return None

    def check_call(
        self, tool_name: str, args: dict[str, Any], result: str
    ) -> str | None:
        """Check if a tool call result has been seen before.

        Args:
            tool_name: Name of the tool called.
            args: Arguments passed to the tool.
            result: The result string from the tool call.

        Returns:
            Dedup marker string if already seen, None if new.
        """
        call_key = self._hash_call(tool_name, args)

        if call_key in self._call_cache:
            entry = self._call_cache[call_key]
            # Verify result hasn't changed (stale check)
            result_hash = hashlib.sha256(result.encode()).hexdigest()[:16]
            if entry.content_hash == result_hash:
                entry.hit_count += 1
                entry.last_seen = time.time()
                self._stats["dedup_hits"] += 1
                self._stats["tokens_saved"] += entry.token_count
                return (
                    f"[Same as previous {tool_name}() call, "
                    f"hash={result_hash[:8]}]"
                )

        # Store new call result
        result_hash = hashlib.sha256(result.encode()).hexdigest()[:16]
        token_estimate = self._estimate_tokens(result)
        self._call_cache[call_key] = DedupEntry(
            key=call_key,
            content_hash=result_hash,
            first_seen=time.time(),
            last_seen=time.time(),
            token_count=token_estimate,
        )
        self._stats["dedup_misses"] += 1

        # Evict old entries if at capacity
        if len(self._call_cache) > self.max_entries:
            self._evict_oldest()

        return None

    def cache_schema(self, tool_name: str, schema: dict[str, Any]) -> None:
        """Cache a tool's full schema for the session."""
        self._schema_cache[tool_name] = schema

    def get_cached_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Retrieve a cached schema by tool name."""
        return self._schema_cache.get(tool_name)

    def has_schema(self, tool_name: str) -> bool:
        """Check if a schema is cached for this tool."""
        return tool_name in self._schema_cache

    def reset(self) -> None:
        """Clear all caches (new session)."""
        self._definitions_cache.clear()
        self._call_cache.clear()
        self._schema_cache.clear()
        self._stats = {
            "dedup_hits": 0,
            "dedup_misses": 0,
            "tokens_saved": 0,
        }

    def _evict_oldest(self) -> None:
        """Evict the oldest entry from call cache."""
        if not self._call_cache:
            return
        oldest_key = min(
            self._call_cache, key=lambda k: self._call_cache[k].last_seen
        )
        del self._call_cache[oldest_key]

    @staticmethod
    def _hash_tools(tools: list[dict[str, Any]]) -> str:
        """Hash a list of tool definitions."""
        import json

        content = json.dumps(tools, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @staticmethod
    def _hash_call(tool_name: str, args: dict[str, Any]) -> str:
        """Hash a tool call (name + args)."""
        import json

        content = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate."""
        if not text:
            return 0
        return int(len(text.split()) * 1.3)

    @property
    def stats(self) -> dict[str, Any]:
        """Return deduplication statistics."""
        return {
            **self._stats,
            "definitions_cached": len(self._definitions_cache),
            "calls_cached": len(self._call_cache),
            "schemas_cached": len(self._schema_cache),
        }
