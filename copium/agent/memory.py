"""Compressed memory store for agent workflows.

Provides a persistent, compressed memory layer for agents that goes beyond
simple session storage. Supports:
- Multi-turn conversation memory with compression
- Semantic retrieval from past interactions
- Priority-based memory retention (important memories persist longer)
- Automatic eviction of low-value memories

ContextCrumb has no memory management. This enables agents to maintain
context across sessions while staying within token budgets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryPriority:
    """Priority levels for memory entries."""

    CRITICAL = 10  # Never evict (errors, user preferences)
    HIGH = 7  # Keep for long sessions (key decisions, tool patterns)
    MEDIUM = 5  # Standard retention (conversation context)
    LOW = 3  # Short retention (verbose tool outputs)
    EPHEMERAL = 1  # Evict first (debug info, intermediate results)


@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""

    key: str
    content: str
    compressed_content: str
    priority: int = MemoryPriority.MEDIUM
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    source: str = ""  # "conversation", "tool_result", "user_input", etc.
    original_tokens: int = 0
    compressed_tokens: int = 0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def staleness(self) -> float:
        """How stale this memory is (seconds since last access)."""
        return time.time() - self.last_accessed

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens == 0:
            return 1.0
        return self.compressed_tokens / self.original_tokens

    @property
    def retention_score(self) -> float:
        """Score for retention priority (higher = keep longer).

        Combines explicit priority with access patterns.
        """
        recency_bonus = max(0, 1.0 - (self.staleness / 3600))  # Decay over 1hr
        frequency_bonus = min(1.0, self.access_count / 10)
        return (self.priority / 10) * 0.5 + recency_bonus * 0.3 + frequency_bonus * 0.2

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "key": self.key,
            "content": self.content,
            "compressed_content": self.compressed_content,
            "priority": self.priority,
            "tags": self.tags,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "source": self.source,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """Deserialize from dictionary."""
        return cls(
            key=data["key"],
            content=data.get("content", ""),
            compressed_content=data.get("compressed_content", ""),
            priority=data.get("priority", MemoryPriority.MEDIUM),
            tags=data.get("tags", []),
            created_at=data.get("created_at", time.time()),
            last_accessed=data.get("last_accessed", time.time()),
            access_count=data.get("access_count", 0),
            source=data.get("source", ""),
            original_tokens=data.get("original_tokens", 0),
            compressed_tokens=data.get("compressed_tokens", 0),
        )


@dataclass
class MemoryStats:
    """Statistics for the memory store."""

    total_entries: int = 0
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0
    evictions: int = 0
    retrievals: int = 0
    stores: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.total_original_tokens == 0:
            return 1.0
        return self.total_compressed_tokens / self.total_original_tokens

    @property
    def tokens_saved(self) -> int:
        return max(0, self.total_original_tokens - self.total_compressed_tokens)


class CompressedMemoryStore:
    """Compressed memory store with semantic retrieval.

    Manages agent memory with automatic compression, priority-based
    retention, and semantic search capabilities.

    Example:
        >>> store = CompressedMemoryStore(max_tokens=50000)
        >>> store.store("file_content", content, compressed, priority=MemoryPriority.HIGH)
        >>> results = store.retrieve("file content about authentication")
        >>> # Returns relevant compressed memories within token budget
    """

    def __init__(
        self,
        max_tokens: int = 50000,
        max_entries: int = 500,
        storage_dir: Path | str | None = None,
    ):
        """Initialize memory store.

        Args:
            max_tokens: Maximum total compressed tokens to retain.
            max_entries: Maximum number of memory entries.
            storage_dir: Optional persistent storage directory.
        """
        self._max_tokens = max_tokens
        self._max_entries = max_entries
        self._entries: dict[str, MemoryEntry] = {}
        self._tag_index: dict[str, list[str]] = {}  # tag -> entry keys
        self._stats = MemoryStats()

        if storage_dir:
            self._storage_dir: Path | None = Path(storage_dir)
            self._storage_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._storage_dir = None

    def store(
        self,
        key: str,
        content: str,
        compressed_content: str,
        *,
        priority: int = MemoryPriority.MEDIUM,
        tags: list[str] | None = None,
        source: str = "",
    ) -> MemoryEntry:
        """Store a memory entry.

        Args:
            key: Unique identifier for this memory.
            content: Original content.
            compressed_content: Compressed version.
            priority: Retention priority.
            tags: Tags for categorization and retrieval.
            source: Source of the memory (conversation, tool, etc).

        Returns:
            The stored MemoryEntry.
        """
        original_tokens = len(content) // 4
        compressed_tokens = len(compressed_content) // 4

        entry = MemoryEntry(
            key=key,
            content=content,
            compressed_content=compressed_content,
            priority=priority,
            tags=tags or [],
            source=source,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
        )

        # Evict if over budget
        while self._total_compressed_tokens + compressed_tokens > self._max_tokens:
            if not self._evict_lowest():
                break

        while len(self._entries) >= self._max_entries:
            if not self._evict_lowest():
                break

        self._entries[key] = entry

        # Update tag index
        for tag in entry.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = []
            if key not in self._tag_index[tag]:
                self._tag_index[tag].append(key)

        self._stats.stores += 1
        self._stats.total_entries = len(self._entries)
        self._stats.total_original_tokens += original_tokens
        self._stats.total_compressed_tokens += compressed_tokens

        return entry

    def retrieve(
        self,
        query: str,
        *,
        max_results: int = 10,
        max_tokens: int | None = None,
        tags: list[str] | None = None,
        min_priority: int = MemoryPriority.EPHEMERAL,
    ) -> list[MemoryEntry]:
        """Retrieve relevant memories by query.

        Uses keyword matching and tag filtering to find relevant memories.

        Args:
            query: Search query.
            max_results: Maximum number of results.
            max_tokens: Maximum total tokens in results.
            tags: Filter by tags.
            min_priority: Minimum priority level.

        Returns:
            List of matching MemoryEntry objects, sorted by relevance.
        """
        self._stats.retrievals += 1
        candidates = self._filter_candidates(tags=tags, min_priority=min_priority)
        scored = self._score_candidates(candidates, query)

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[MemoryEntry] = []
        total_tokens = 0
        token_budget = max_tokens or self._max_tokens

        for score, entry in scored[:max_results]:
            if score <= 0:
                break
            if total_tokens + entry.compressed_tokens > token_budget:
                break

            entry.last_accessed = time.time()
            entry.access_count += 1
            results.append(entry)
            total_tokens += entry.compressed_tokens

        return results

    def get(self, key: str) -> MemoryEntry | None:
        """Get a specific memory entry by key.

        Args:
            key: Memory entry key.

        Returns:
            MemoryEntry or None.
        """
        entry = self._entries.get(key)
        if entry:
            entry.last_accessed = time.time()
            entry.access_count += 1
            self._stats.retrievals += 1
        return entry

    def delete(self, key: str) -> bool:
        """Delete a memory entry.

        Args:
            key: Key to delete.

        Returns:
            True if deleted.
        """
        entry = self._entries.pop(key, None)
        if entry:
            for tag in entry.tags:
                if tag in self._tag_index:
                    self._tag_index[tag] = [
                        k for k in self._tag_index[tag] if k != key
                    ]
            self._stats.total_entries = len(self._entries)
            return True
        return False

    def get_by_tags(self, tags: list[str]) -> list[MemoryEntry]:
        """Get all memories matching any of the given tags.

        Args:
            tags: Tags to search for.

        Returns:
            List of matching entries.
        """
        keys: set[str] = set()
        for tag in tags:
            keys.update(self._tag_index.get(tag, []))
        return [self._entries[k] for k in keys if k in self._entries]

    @property
    def stats(self) -> MemoryStats:
        """Get current memory store statistics."""
        return self._stats

    @property
    def total_entries(self) -> int:
        """Total number of stored entries."""
        return len(self._entries)

    def persist(self) -> None:
        """Persist all entries to disk (if storage_dir configured)."""
        if not self._storage_dir:
            return

        data = {
            "entries": {k: v.to_dict() for k, v in self._entries.items()},
            "stats": {
                "stores": self._stats.stores,
                "retrievals": self._stats.retrievals,
                "evictions": self._stats.evictions,
            },
        }
        path = self._storage_dir / "memory_store.json"
        path.write_text(json.dumps(data, indent=2))

    def load(self) -> None:
        """Load entries from disk (if storage_dir configured)."""
        if not self._storage_dir:
            return

        path = self._storage_dir / "memory_store.json"
        if not path.exists():
            return

        data = json.loads(path.read_text())
        for key, entry_data in data.get("entries", {}).items():
            self._entries[key] = MemoryEntry.from_dict(entry_data)
            for tag in self._entries[key].tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = []
                self._tag_index[tag].append(key)

        self._stats.total_entries = len(self._entries)

    @property
    def _total_compressed_tokens(self) -> int:
        """Total compressed tokens across all entries."""
        return sum(e.compressed_tokens for e in self._entries.values())

    def _filter_candidates(
        self,
        *,
        tags: list[str] | None = None,
        min_priority: int = MemoryPriority.EPHEMERAL,
    ) -> list[MemoryEntry]:
        """Filter entries by tags and priority."""
        candidates = [
            e for e in self._entries.values() if e.priority >= min_priority
        ]

        if tags:
            tag_keys: set[str] = set()
            for tag in tags:
                tag_keys.update(self._tag_index.get(tag, []))
            candidates = [e for e in candidates if e.key in tag_keys]

        return candidates

    def _score_candidates(
        self,
        candidates: list[MemoryEntry],
        query: str,
    ) -> list[tuple[float, MemoryEntry]]:
        """Score candidates against a query using keyword matching."""
        query_words = set(query.lower().split())
        scored: list[tuple[float, MemoryEntry]] = []

        for entry in candidates:
            score = 0.0
            content_lower = entry.compressed_content.lower()
            key_lower = entry.key.lower()

            # Keyword matching
            for word in query_words:
                if word in content_lower:
                    score += 1.0
                if word in key_lower:
                    score += 0.5

            # Tag matching
            for tag in entry.tags:
                if tag.lower() in query_words:
                    score += 2.0

            # Priority bonus
            score *= (entry.priority / 10)

            # Recency bonus
            recency = max(0, 1.0 - (entry.staleness / 7200))
            score += recency * 0.5

            scored.append((score, entry))

        return scored

    def _evict_lowest(self) -> bool:
        """Evict the entry with the lowest retention score.

        Returns:
            True if an entry was evicted.
        """
        if not self._entries:
            return False

        # Find lowest retention score entry
        lowest_key = min(
            self._entries.keys(),
            key=lambda k: self._entries[k].retention_score,
        )
        entry = self._entries[lowest_key]

        # Never evict CRITICAL entries
        if entry.priority >= MemoryPriority.CRITICAL:
            return False

        self.delete(lowest_key)
        self._stats.evictions += 1
        return True

    def _make_key(self, content: str) -> str:
        """Generate a unique key from content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
