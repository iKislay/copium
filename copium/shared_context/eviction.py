"""Eviction policies for SharedContext persistent store.

Implements TTL-based expiration and LRU eviction strategies
to manage storage capacity.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class EvictionPolicy(Enum):
    """Available eviction strategies."""

    TTL = "ttl"  # Time-to-live based
    LRU = "lru"  # Least recently used
    LFU = "lfu"  # Least frequently used
    FIFO = "fifo"  # First in, first out


@dataclass
class EvictionConfig:
    """Configuration for eviction behavior.

    Args:
        policy: Primary eviction strategy (default: TTL + LRU fallback).
        ttl_seconds: Default TTL for entries in seconds.
        max_entries: Maximum entries before forced eviction.
        eviction_batch_size: How many entries to evict at once when over capacity.
        min_access_count: Minimum access count to protect from LFU eviction.
    """

    policy: EvictionPolicy = EvictionPolicy.LRU
    ttl_seconds: int = 3600
    max_entries: int = 1000
    eviction_batch_size: int = 10
    min_access_count: int = 3


class EvictionManager:
    """Manages eviction decisions for the persistent store.

    Combines TTL expiration (always active) with a configurable
    capacity-based eviction policy.
    """

    def __init__(self, config: EvictionConfig | None = None) -> None:
        self._config = config or EvictionConfig()

    @property
    def config(self) -> EvictionConfig:
        return self._config

    @property
    def ttl_seconds(self) -> int:
        return self._config.ttl_seconds

    @property
    def max_entries(self) -> int:
        return self._config.max_entries

    def compute_expiry(self, ttl_override: int | None = None) -> float:
        """Compute expiry timestamp for a new entry.

        Args:
            ttl_override: Custom TTL in seconds, or None for default.

        Returns:
            Unix timestamp when the entry should expire.
        """
        ttl = ttl_override if ttl_override is not None else self._config.ttl_seconds
        return time.time() + ttl

    def is_expired(self, expires_at: float) -> bool:
        """Check if an entry has expired."""
        return time.time() > expires_at

    def should_evict(self, current_count: int) -> bool:
        """Check if eviction is needed based on capacity."""
        return current_count >= self._config.max_entries

    def eviction_count(self, current_count: int) -> int:
        """How many entries to evict to restore capacity."""
        if current_count < self._config.max_entries:
            return 0
        return min(
            current_count - self._config.max_entries + self._config.eviction_batch_size,
            current_count,
        )

    def order_by_clause(self) -> str:
        """SQL ORDER BY clause for selecting eviction candidates.

        Returns the appropriate ordering based on the configured policy.
        """
        if self._config.policy == EvictionPolicy.LRU:
            return "ORDER BY last_accessed ASC"
        elif self._config.policy == EvictionPolicy.LFU:
            return "ORDER BY access_count ASC, last_accessed ASC"
        elif self._config.policy == EvictionPolicy.FIFO:
            return "ORDER BY created_at ASC"
        else:
            # TTL-only: evict by nearest expiry
            return "ORDER BY expires_at ASC"
