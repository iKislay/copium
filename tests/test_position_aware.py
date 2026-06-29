"""Unit tests for position-aware compression module."""

import pytest

from copium.transforms.position_aware import (
    Zone,
    PositionWeightConfig,
    compute_position_benefit,
    optimize_kept_order,
    position_keep_priority,
    position_weighted_score,
    position_zone,
)


class TestPositionZone:
    """Tests for the position_zone classifier."""

    def test_beginning_zone(self):
        assert position_zone(0, 100) == Zone.BEGINNING
        assert position_zone(9, 100) == Zone.BEGINNING

    def test_mid_beginning_zone(self):
        assert position_zone(10, 100) == Zone.MID_BEGINNING
        assert position_zone(29, 100) == Zone.MID_BEGINNING

    def test_middle_zone(self):
        assert position_zone(30, 100) == Zone.MIDDLE
        assert position_zone(50, 100) == Zone.MIDDLE
        assert position_zone(69, 100) == Zone.MIDDLE

    def test_mid_end_zone(self):
        assert position_zone(70, 100) == Zone.MID_END
        assert position_zone(89, 100) == Zone.MID_END

    def test_end_zone(self):
        assert position_zone(90, 100) == Zone.END
        assert position_zone(99, 100) == Zone.END

    def test_empty_context(self):
        assert position_zone(0, 0) == Zone.MIDDLE

    def test_small_context(self):
        # With 3 items: pos 0 = 0% (Beginning), pos 1 = 33% (Middle)
        assert position_zone(0, 3) == Zone.BEGINNING
        assert position_zone(1, 3) == Zone.MIDDLE


class TestZoneProperties:
    """Tests for Zone enum properties."""

    def test_attention_quality_ordering(self):
        # Edges should have higher quality than middle
        assert Zone.BEGINNING.attention_quality > Zone.MIDDLE.attention_quality
        assert Zone.END.attention_quality > Zone.MIDDLE.attention_quality

    def test_is_degraded(self):
        assert Zone.MIDDLE.is_degraded
        assert not Zone.BEGINNING.is_degraded
        assert not Zone.END.is_degraded

    def test_is_high_attention(self):
        assert Zone.BEGINNING.is_high_attention
        assert Zone.END.is_high_attention
        assert not Zone.MIDDLE.is_high_attention
        assert not Zone.MID_BEGINNING.is_high_attention


class TestPositionWeightConfig:
    """Tests for PositionWeightConfig."""

    def test_default_is_disabled(self):
        config = PositionWeightConfig()
        assert config.is_disabled
        assert config.position_weight == 0.0
        assert not config.enable_reordering

    def test_enabled_factory(self):
        config = PositionWeightConfig.enabled(0.7)
        assert not config.is_disabled
        assert config.position_weight == 0.7
        assert config.enable_reordering

    def test_enabled_clamps_weight(self):
        config = PositionWeightConfig.enabled(2.0)
        assert config.position_weight == 1.0

        config = PositionWeightConfig.enabled(-1.0)
        assert config.position_weight == 0.0


class TestComputePositionBenefit:
    """Tests for compute_position_benefit."""

    def test_disabled_returns_zero(self):
        config = PositionWeightConfig()
        assert compute_position_benefit(50, 5, 100, config) == 0.0

    def test_middle_to_beginning_positive(self):
        config = PositionWeightConfig.enabled(1.0)
        benefit = compute_position_benefit(50, 5, 100, config)
        assert benefit > 0.0
        assert benefit == 0.3

    def test_middle_to_end_positive(self):
        config = PositionWeightConfig.enabled(1.0)
        benefit = compute_position_benefit(50, 95, 100, config)
        assert benefit > 0.0

    def test_beginning_to_middle_negative(self):
        config = PositionWeightConfig.enabled(1.0)
        benefit = compute_position_benefit(5, 50, 100, config)
        assert benefit < 0.0
        assert benefit == -0.2

    def test_stays_middle_neutral(self):
        config = PositionWeightConfig.enabled(1.0)
        benefit = compute_position_benefit(40, 60, 100, config)
        assert benefit == 0.0

    def test_weight_scales_benefit(self):
        config_half = PositionWeightConfig.enabled(0.5)
        config_full = PositionWeightConfig.enabled(1.0)
        half = compute_position_benefit(50, 5, 100, config_half)
        full = compute_position_benefit(50, 5, 100, config_full)
        assert abs(half - full * 0.5) < 1e-10


class TestPositionWeightedScore:
    """Tests for position_weighted_score."""

    def test_disabled_returns_base(self):
        config = PositionWeightConfig()
        assert position_weighted_score(0.8, 50, 5, 100, config) == 0.8

    def test_middle_to_beginning_boosts_score(self):
        config = PositionWeightConfig.enabled(1.0)
        score = position_weighted_score(0.8, 50, 5, 100, config)
        assert score > 0.8  # Should be boosted

    def test_beginning_to_middle_reduces_score(self):
        config = PositionWeightConfig.enabled(1.0)
        score = position_weighted_score(0.8, 5, 50, 100, config)
        assert score < 0.8  # Should be reduced

    def test_never_negative(self):
        config = PositionWeightConfig.enabled(1.0)
        score = position_weighted_score(0.1, 5, 50, 100, config)
        assert score >= 0.0


class TestPositionKeepPriority:
    """Tests for position_keep_priority."""

    def test_edges_higher_than_middle(self):
        beginning = position_keep_priority(5, 100)
        middle = position_keep_priority(50, 100)
        end = position_keep_priority(95, 100)
        assert beginning > middle
        assert end > middle


class TestOptimizeKeptOrder:
    """Tests for optimize_kept_order (bookend strategy)."""

    def test_disabled_preserves_order(self):
        config = PositionWeightConfig()
        items = [(0, 0.9), (1, 0.5), (2, 0.7), (3, 0.3)]
        result = optimize_kept_order(items, config)
        assert result == [0, 1, 2, 3]

    def test_empty_input(self):
        config = PositionWeightConfig.enabled(1.0)
        result = optimize_kept_order([], config)
        assert result == []

    def test_two_items_unchanged(self):
        config = PositionWeightConfig.enabled(1.0)
        items = [(0, 0.9), (1, 0.5)]
        result = optimize_kept_order(items, config)
        assert result == [0, 1]

    def test_bookend_places_highest_at_edges(self):
        config = PositionWeightConfig(
            position_weight=1.0,
            enable_reordering=True,
            max_reorder_fraction=1.0,
        )
        items = [(0, 0.2), (1, 0.9), (2, 0.5), (3, 0.8)]
        result = optimize_kept_order(items, config)
        # Highest score (idx=1, score=0.9) → first position
        # Second highest (idx=3, score=0.8) → last position
        assert result[0] == 1
        assert result[-1] == 3

    def test_respects_max_reorder_fraction(self):
        config = PositionWeightConfig(
            position_weight=1.0,
            enable_reordering=True,
            max_reorder_fraction=0.5,
        )
        # 4 items, max_reorder_fraction=0.5 → only 2 items reordered
        items = [(0, 0.1), (1, 0.9), (2, 0.5), (3, 0.8)]
        result = optimize_kept_order(items, config)
        assert len(result) == 4
