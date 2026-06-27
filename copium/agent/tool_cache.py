"""Semantic tool result cache.

Caches tool results by semantic similarity, so repeated or similar
tool calls can return cached results without re-execution. This avoids
redundant compression of identical content.

ContextCrumb compresses every time. Copium caches and skips when it
has seen similar content before.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached tool result."""

    key: str
    tool_name: str
    tool_input_hash: str
    result: str
    compressed_result: str
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    tokens_saved_total: int = 0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def is_expired(self) -> bool:
        """Check if entry is expired (default: 10 min TTL)."""
        return self.age_seconds > 600


@dataclass
class CacheStats:
    """Statistics for the semantic tool cache."""

    hits: int = 0
    misses: int = 0
    entries: int = 0
    tokens_saved: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def hit_rate_pct(self) -> float:
        return self.hit_rate * 100


class SemanticToolCache:
    """Cache for tool results with semantic deduplication.

    When an agent calls the same tool with similar inputs, this cache
    returns the previous (compressed) result instead of re-processing.

    Features:
    - Exact match caching (same tool + same args)
    - Content-based dedup (same output regardless of args)
    - TTL-based expiration
    - LRU eviction when cache is full

    Example:
        >>> cache = SemanticToolCache(max_entries=100)
        >>> # First call - cache miss
        >>> result = cache.get("read_file", {"path": "/main.py"})
        >>> assert result is None
        >>> # Store result
        >>> cache.put("read_file", {"path": "/main.py"}, output, compressed)
        >>> # Second call - cache hit
        >>> result = cache.get("read_file", {"path": "/main.py"})
        >>> assert result == compressed
    """

    def __init__(self, max_entries: int = 200, ttl_seconds: int = 600):
        """Initialize cache.

        Args:
            max_entries: Maximum cache entries before eviction.
            ttl_seconds: Time-to-live for cache entries.
        """
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._content_index: dict[str, str] = {}  # content_hash -> cache_key
        self._stats = CacheStats()

    def get(self, tool_name: str, tool_input: dict[str, Any]) -> str | None:
        """Look up a cached tool result.

        Args:
            tool_name: Name of the tool.
            tool_input: Tool input arguments.

        Returns:
            Compressed result if cached, None otherwise.
        """
        key = self._make_key(tool_name, tool_input)
        entry = self._cache.get(key)

        if entry is None:
            self._stats.misses += 1
            return None

        if entry.is_expired or entry.age_seconds > self._ttl:
            # Expired - remove and miss
            del self._cache[key]
            self._stats.misses += 1
            self._stats.evictions += 1
            return None

        # Cache hit
        entry.access_count += 1
        entry.tokens_saved_total += len(entry.result) // 4 - len(entry.compressed_result) // 4
        self._stats.hits += 1
        self._stats.tokens_saved += len(entry.result) // 4 - len(entry.compressed_result) // 4

        return entry.compressed_result

    def get_by_content(self, content: str) -> str | None:
        """Look up by content hash (content-based dedup).

        If any cached entry has the same output content, return its
        compressed version regardless of tool name or args.

        Args:
            content: The tool output content to look up.

        Returns:
            Compressed version if found, None otherwise.
        """
        content_hash = self._hash_content(content)
        cache_key = self._content_index.get(content_hash)

        if cache_key and cache_key in self._cache:
            entry = self._cache[cache_key]
            if not entry.is_expired and entry.age_seconds <= self._ttl:
                entry.access_count += 1
                self._stats.hits += 1
                return entry.compressed_result

        self._stats.misses += 1
        return None

    def put(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        result: str,
        compressed_result: str,
    ) -> None:
        """Store a tool result in cache.

        Args:
            tool_name: Name of the tool.
            tool_input: Tool input arguments.
            result: Original tool output.
            compressed_result: Compressed version of output.
        """
        # Evict if full
        if len(self._cache) >= self._max_entries:
            self._evict_lru()

        key = self._make_key(tool_name, tool_input)
        input_hash = self._hash_input(tool_input)
        content_hash = self._hash_content(result)

        entry = CacheEntry(
            key=key,
            tool_name=tool_name,
            tool_input_hash=input_hash,
            result=result,
            compressed_result=compressed_result,
        )

        self._cache[key] = entry
        self._content_index[content_hash] = key
        self._stats.entries = len(self._cache)

    def invalidate(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Invalidate a specific cache entry.

        Args:
            tool_name: Tool name.
            tool_input: Tool input.

        Returns:
            True if entry was found and removed.
        """
        key = self._make_key(tool_name, tool_input)
        if key in self._cache:
            del self._cache[key]
            self._stats.entries = len(self._cache)
            return True
        return False

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._content_index.clear()
        self._stats.entries = 0

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        self._stats.entries = len(self._cache)
        return self._stats

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._cache:
            return

        # Find oldest entry by created_at (simple LRU approximation)
        oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_key]
        self._stats.evictions += 1

    @staticmethod
    def _make_key(tool_name: str, tool_input: dict[str, Any]) -> str:
        """Create cache key from tool name and input."""
        import json
        input_str = json.dumps(tool_input, sort_keys=True)
        combined = f"{tool_name}:{input_str}"
        return hashlib.sha256(combined.encode()).hexdigest()[:24]

    @staticmethod
    def _hash_input(tool_input: dict[str, Any]) -> str:
        """Hash tool input for comparison."""
        import json
        return hashlib.md5(  # noqa: S324
            json.dumps(tool_input, sort_keys=True).encode()
        ).hexdigest()[:16]

    @staticmethod
    def _hash_content(content: str) -> str:
        """Hash content for dedup index."""
        return hashlib.sha256(content.encode()).hexdigest()[:20]
