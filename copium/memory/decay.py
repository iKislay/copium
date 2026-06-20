"""Decaying Persistent Memory — pre-computed expiration architecture.

Instead of running background decay loops or computing S(t) at query time,
we calculate the exact expiration timestamp at insertion/reinforcement.
The read path is a pure O(1) index scan:

    SELECT ... FROM memories
    WHERE expires_at > unixepoch()
    ORDER BY last_accessed_at DESC

Math:
    S(t) = S₀ · e^(-λt)
    t_expire = -ln(T / S₀) / λ   (in days, converted to seconds)

Reinforcement:
    When a memory is referenced, push expires_at forward:
    new_expires_at = now + (base_lifespan × multiplier)

Garbage Collection:
    Lazy background task runs DELETE WHERE expires_at < unixepoch()
    every 24h to reclaim disk space. No active decay logic.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecayConfig:
    """Configuration for memory decay.

    Attributes:
        enabled: Whether decay is active.
        decay_lambda: Decay constant λ. Default: ln(2)/7 ≈ 0.099 (7-day half-life).
        threshold: Drop memories below this S(t) value. Default: 0.1.
        reinforcement_multiplier: Lifespan boost on reference. Default: 1.2 (20%).
        gc_interval: Seconds between garbage collection sweeps. Default: 86400 (24h).
        default_lifespan_days: Fallback lifespan for legacy rows without base_importance.
    """

    enabled: bool = True
    decay_lambda: float = math.log(2) / 7  # 7-day half-life
    threshold: float = 0.1
    reinforcement_multiplier: float = 1.2
    gc_interval: int = 86400
    default_lifespan_days: float = 7.0


def compute_expiration(
    base_importance: float,
    decay_lambda: float,
    threshold: float,
) -> float:
    """Compute the lifespan in seconds from now until S(t) hits threshold.

    Given S(t) = S₀ · e^(-λt), solve for t when S(t) = T:
        t_expire = -ln(T / S₀) / λ   (days)

    Args:
        base_importance: S₀ — the original importance score (0.0, 1.0].
        decay_lambda: λ — the decay constant.
        threshold: T — the cutoff below which the memory is dropped.

    Returns:
        Lifespan in seconds from now.

    Raises:
        ValueError: If base_importance <= 0 or threshold >= base_importance.
    """
    if base_importance <= 0:
        raise ValueError(f"base_importance must be > 0, got {base_importance}")
    if threshold >= base_importance:
        raise ValueError(
            f"threshold ({threshold}) must be < base_importance ({base_importance})"
        )
    if decay_lambda <= 0:
        raise ValueError(f"decay_lambda must be > 0, got {decay_lambda}")

    t_days = -math.log(threshold / base_importance) / decay_lambda
    return t_days * 86400


def compute.expires_at(
    base_importance: float,
    decay_lambda: float,
    threshold: float,
    now: float | None = None,
) -> int:
    """Compute the absolute expiration Unix timestamp.

    Args:
        base_importance: S₀ — the original importance score.
        decay_lambda: λ — the decay constant.
        threshold: T — the cutoff.
        now: Current Unix timestamp (defaults to time.time()).

    Returns:
        Unix timestamp (integer) when the memory expires.
    """
    if now is None:
        now = time.time()
    lifespan = compute_expiration(base_importance, decay_lambda, threshold)
    return int(now + lifespan)


def reinforce_expiration(
    current_expires_at: int,
    base_lifespan: float,
    multiplier: float = 1.2,
    now: float | None = None,
) -> int:
    """Shift expiration forward when a memory is referenced.

    The new expiration is: now + (base_lifespan × multiplier).
    This resets t=0 for the memory, proving its continued relevance.

    Args:
        current_expires_at: Current expiration timestamp (unused in calculation,
            kept for API consistency and logging).
        base_lifespan: The original lifespan in seconds (from compute_expiration).
        multiplier: Lifespan boost factor. Default: 1.2 (20% extension).
        now: Current Unix timestamp (defaults to time.time()).

    Returns:
        New expiration Unix timestamp.
    """
    if now is None:
        now = time.time()
    return int(now + (base_lifespan * multiplier))


def compute_base_lifespan(
    base_importance: float,
    decay_lambda: float,
    threshold: float,
) -> float:
    """Compute the base lifespan in seconds for a memory.

    Used for reinforcement calculations where we need the original
    lifespan duration, not the absolute expiration timestamp.

    Args:
        base_importance: S₀ — the original importance score.
        decay_lambda: λ — the decay constant.
        threshold: T — the cutoff.

    Returns:
        Lifespan in seconds.
    """
    return compute_expiration(base_importance, decay_lambda, threshold)


async def gc_expired(db_path: Path) -> int:
    """Lazy garbage collector — hard delete expired memories.

    DELETE WHERE expires_at < unixepoch()
    This reclaims disk space. No active decay logic — the read query
    naturally excludes expired rows via the index.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        Number of rows deleted.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < unixepoch()"
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info("Memory GC: deleted %d expired memories", deleted)
        return deleted
    except Exception as e:
        logger.error("Memory GC failed: %s", e)
        return 0


async def backfill_legacy_memories(db_path: Path, config: DecayConfig) -> int:
    """Backfill expires_at for legacy rows that have NULL.

    Gives legacy memories a flat default_lifespan_days grace period
    so they aren't instantly filtered out by the read query.

    Args:
        db_path: Path to the SQLite database.
        config: Decay configuration.

    Returns:
        Number of rows updated.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        lifespan_seconds = int(config.default_lifespan_days * 86400)
        cursor = conn.execute(
            """
            UPDATE memories
            SET base_importance = COALESCE(base_importance, importance, 0.5),
                expires_at = unixepoch() + ?
            WHERE expires_at IS NULL
            """,
            (lifespan_seconds,),
        )
        updated = cursor.rowcount
        conn.commit()
        conn.close()
        if updated > 0:
            logger.info(
                "Memory decay: backfilled %d legacy rows with %d-day grace period",
                updated,
                config.default_lifespan_days,
            )
        return updated
    except Exception as e:
        logger.error("Memory decay backfill failed: %s", e)
        return 0
