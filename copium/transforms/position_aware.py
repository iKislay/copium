"""Position-aware compression for the 'Lost in the Middle' problem.

This module provides utilities to account for the U-shaped attention
degradation in LLM context windows (Liu et al., 2023). LLMs attend
strongly to the beginning and end of context but degrade in the middle.

Position-aware compression exploits this by:
1. Classifying positions into attention zones
2. Weighting importance scores by position quality
3. Reordering compressed items to place important content at edges

Usage:
    from copium.transforms.position_aware import (
        Zone,
        position_zone,
        PositionWeightConfig,
        position_weighted_score,
        optimize_kept_order,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Sequence, Tuple


class Zone(Enum):
    """Attention zone within a context window.

    Based on empirical findings that LLMs exhibit a U-shaped attention
    curve across the context window.
    """

    BEGINNING = "beginning"  # 0-10%: highest attention
    MID_BEGINNING = "mid_beginning"  # 10-30%: moderate
    MIDDLE = "middle"  # 30-70%: degraded
    MID_END = "mid_end"  # 70-90%: recovering
    END = "end"  # 90-100%: high attention

    @property
    def attention_quality(self) -> float:
        """Approximate attention quality multiplier for this zone."""
        return _ZONE_QUALITY[self]

    @property
    def is_degraded(self) -> bool:
        """True if this zone has degraded attention."""
        return self == Zone.MIDDLE

    @property
    def is_high_attention(self) -> bool:
        """True if this zone has high attention quality."""
        return self in (Zone.BEGINNING, Zone.END)


_ZONE_QUALITY = {
    Zone.BEGINNING: 0.95,
    Zone.MID_BEGINNING: 0.78,
    Zone.MIDDLE: 0.55,
    Zone.MID_END: 0.75,
    Zone.END: 0.93,
}


def position_zone(position: int, context_length: int) -> Zone:
    """Classify a position into the appropriate attention zone.

    Args:
        position: Zero-based index in the context.
        context_length: Total number of items in the context.

    Returns:
        The Zone corresponding to the relative position.
    """
    if context_length == 0:
        return Zone.MIDDLE

    relative = position / context_length

    if relative < 0.10:
        return Zone.BEGINNING
    elif relative < 0.30:
        return Zone.MID_BEGINNING
    elif relative < 0.70:
        return Zone.MIDDLE
    elif relative < 0.90:
        return Zone.MID_END
    else:
        return Zone.END


@dataclass
class PositionWeightConfig:
    """Configuration for position-aware compression.

    When position_weight is 0.0 (default), all position-aware functions
    reduce to identity/no-op, preserving backward compatibility.
    """

    position_weight: float = 0.0
    """Master weight for position influence. 0.0 disables, 1.0 full effect."""

    middle_to_edge_bonus: float = 0.3
    """Bonus when moving important content from middle to edges."""

    edge_to_middle_penalty: float = -0.2
    """Penalty when content moves from edges to middle."""

    stable_high_attention_bonus: float = 0.05
    """Small bonus for content staying in high-attention zones."""

    enable_reordering: bool = False
    """Whether to reorder items within compressed blocks."""

    max_reorder_fraction: float = 0.5
    """Max fraction of items that can be reordered."""

    @property
    def is_disabled(self) -> bool:
        """True if position awareness is effectively disabled."""
        return self.position_weight == 0.0

    @classmethod
    def enabled(cls, weight: float = 0.5) -> "PositionWeightConfig":
        """Create a config with position awareness enabled."""
        w = max(0.0, min(1.0, weight))
        return cls(position_weight=w, enable_reordering=w > 0.0)


def compute_position_benefit(
    original_pos: int,
    target_pos: int,
    context_len: int,
    config: PositionWeightConfig,
) -> float:
    """Compute benefit/penalty of moving content between positions.

    Returns a value in approximately [-0.2, 0.3]:
    - Positive: content moves to a better attention zone
    - Zero: no meaningful change
    - Negative: content moves to a worse zone
    """
    if config.is_disabled:
        return 0.0

    original_zone = position_zone(original_pos, context_len)
    target_zone = position_zone(target_pos, context_len)

    # Middle → edge transitions
    if original_zone == Zone.MIDDLE and target_zone in (Zone.BEGINNING, Zone.END):
        raw = config.middle_to_edge_bonus
    elif original_zone == Zone.MIDDLE and target_zone in (
        Zone.MID_BEGINNING,
        Zone.MID_END,
    ):
        raw = config.middle_to_edge_bonus * 0.5
    elif original_zone == Zone.MIDDLE and target_zone == Zone.MIDDLE:
        raw = 0.0
    # Edge → middle transitions
    elif original_zone in (Zone.BEGINNING, Zone.END) and target_zone == Zone.MIDDLE:
        raw = config.edge_to_middle_penalty
    elif original_zone in (Zone.MID_BEGINNING, Zone.MID_END) and target_zone == Zone.MIDDLE:
        raw = config.edge_to_middle_penalty * 0.5
    # Staying in high-attention zones
    elif original_zone == target_zone and original_zone in (Zone.BEGINNING, Zone.END):
        raw = config.stable_high_attention_bonus
    else:
        raw = 0.0

    return raw * config.position_weight


def position_weighted_score(
    base_score: float,
    original_pos: int,
    target_pos: int,
    context_len: int,
    config: PositionWeightConfig,
) -> float:
    """Apply position-dependent weight to a content importance score.

    When config.position_weight is 0.0, returns base_score unchanged.
    """
    if config.is_disabled:
        return base_score

    benefit = compute_position_benefit(original_pos, target_pos, context_len, config)
    weighted = base_score * (1.0 + benefit)
    return max(0.0, weighted)


def position_keep_priority(position: int, context_len: int) -> float:
    """Score how much an item benefits from being kept based on its position.

    Items in high-attention zones get higher keep priority. Returns a
    value in [0.5, 1.0] representing the attention quality at that position.
    """
    zone = position_zone(position, context_len)
    return zone.attention_quality


def optimize_kept_order(
    items_with_scores: Sequence[Tuple[int, float]],
    config: PositionWeightConfig,
) -> List[int]:
    """Reorder kept items using the bookend strategy.

    Places highest-importance items at the beginning and end of the
    block (high-attention zones), with lower-importance items in the
    middle.

    Args:
        items_with_scores: Pairs of (original_index, importance_score).
        config: Position weight configuration.

    Returns:
        Reordered list of original indices. If disabled, returns indices
        in their original order.
    """
    if config.is_disabled or not config.enable_reordering or not items_with_scores:
        return [idx for idx, _ in items_with_scores]

    n = len(items_with_scores)
    if n <= 2:
        return [idx for idx, _ in items_with_scores]

    # Determine how many items to reorder
    max_reorder = min(n, int(n * config.max_reorder_fraction + 0.5) or 1)

    # Sort by score descending
    scored = sorted(items_with_scores, key=lambda x: x[1], reverse=True)

    to_reorder = scored[:max_reorder]
    keep_in_place = sorted([idx for idx, _ in scored[max_reorder:]])

    # Bookend strategy: alternate placing items at front and back
    result = [0] * max_reorder
    front = 0
    back = max_reorder - 1
    place_front = True

    for idx, _ in to_reorder:
        if place_front:
            result[front] = idx
            front += 1
        else:
            result[back] = idx
            if back > 0:
                back -= 1
        place_front = not place_front

    result.extend(keep_in_place)
    return result
