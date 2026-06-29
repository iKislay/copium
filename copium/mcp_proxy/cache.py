"""Session-level cache for tool schemas and compressed definitions.

Provides TTL-based caching for tool schemas that rarely change within
a session. Avoids re-compressing the same tool definitions on every
tools/list request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    """A cached item with TTL tracking."""

    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    ttl_seconds: float = 300.0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds

    def touch(self) -> None:
        self.last_accessed = time.time()
        self.access_count += 1


class ProxyCache:
    """In-memory cache for the MCP proxy.

    Caches:
    - Compressed tool definitions (avoid re-compression)
    - Tool schemas (sent once per session)
    - Upstream server tool lists (refresh on TTL expiry)
    """

    def __init__(self, default_ttl: float = 300.0, max_entries: int = 500) -> None:
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._store: dict[str, CacheEntry] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }

    def get(self, key: str) -> Any | None:
        """Get a value from cache, returning None if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        if entry.is_expired:
            del self._store[key]
            self._stats["misses"] += 1
            return None

        entry.touch()
        self._stats["hits"] += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Set a value in cache with optional custom TTL."""
        if len(self._store) >= self._max_entries:
            self._evict_expired()
            if len(self._store) >= self._max_entries:
                self._evict_lru()

        self._store[key] = CacheEntry(
            key=key,
            value=value,
            ttl_seconds=ttl if ttl is not None else self._default_ttl,
        )

    def invalidate(self, key: str) -> bool:
        """Remove a specific key from cache."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all keys starting with a prefix."""
        keys_to_remove = [k for k in self._store if k.startswith(prefix)]
        for key in keys_to_remove:
            del self._store[key]
        return len(keys_to_remove)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()

    def _evict_expired(self) -> None:
        """Remove all expired entries."""
        expired = [k for k, v in self._store.items() if v.is_expired]
        for key in expired:
            del self._store[key]
            self._stats["evictions"] += 1

    def _evict_lru(self) -> None:
        """Evict least-recently-used entry."""
        if not self._store:
            return
        lru_key = min(self._store, key=lambda k: self._store[k].last_accessed)
        del self._store[lru_key]
        self._stats["evictions"] += 1

    @property
    def size(self) -> int:
        """Number of entries currently in cache."""
        return len(self._store)

    @property
    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0.0
        return {
            **self._stats,
            "size": self.size,
            "hit_rate_percent": round(hit_rate, 1),
        }
