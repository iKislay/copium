"""Tests for agent_context smart zone calculator."""

import pytest

from copium.agent_context.smart_zone import (
    CompressionLevel,
    SmartZone,
    SmartZoneBudget,
    SmartZoneConfig,
)


class TestSmartZoneConfig:
    """Test Smart Zone configuration."""

    def test_default_config(self):
        config = SmartZoneConfig()
        assert config.context_window == 200_000
        assert config.model_family == "claude-4"
        assert config.quantization == "cloud"
        assert config.task_type == "implementation"

    def test_custom_config(self):
        config = SmartZoneConfig(
            context_window=128_000,
            model_family="gpt-4o",
            quantization="fp16",
            task_type="exploration",
        )
        assert config.context_window == 128_000

    def test_invalid_context_window(self):
        with pytest.raises(ValueError, match="context_window must be positive"):
            SmartZoneConfig(context_window=0)


class TestSmartZone:
    """Test Smart Zone budget calculation and enforcement."""

    def test_default_budget(self):
        zone = SmartZone(SmartZoneConfig())
        budget = zone.calculate_budget()
        # 200K * 0.40 (cloud) * 1.00 (implementation) * 1.00 (claude-4) = 80K
        assert budget.smart_zone_tokens == 80_000
        assert budget.total_tokens == 200_000

    def test_local_quantized_budget(self):
        config = SmartZoneConfig(
            context_window=200_000,
            model_family="local-7b",
            quantization="q4_0",
            task_type="exploration",
        )
        zone = SmartZone(config)
        budget = zone.calculate_budget()
        # 200K * 0.20 (q4_0) * 0.80 (exploration) * 0.70 (local-7b) = 22,400
        assert budget.smart_zone_tokens == 22_400

    def test_phase_allocations_sum_to_100(self):
        zone = SmartZone(SmartZoneConfig())
        budget = zone.calculate_budget()
        total_allocated = (
            budget.orientation_budget
            + budget.exploration_budget
            + budget.implementation_budget
            + budget.verification_budget
            + budget.reserved_for_reasoning
        )
        # Should be approximately the smart zone (rounding differences)
        assert abs(total_allocated - budget.smart_zone_tokens) < 5

    def test_remaining_budget(self):
        zone = SmartZone(SmartZoneConfig())
        remaining = zone.remaining_budget(50_000)
        assert remaining == 30_000  # 80K - 50K

    def test_remaining_budget_negative_when_exceeded(self):
        zone = SmartZone(SmartZoneConfig())
        remaining = zone.remaining_budget(100_000)
        assert remaining == -20_000

    def test_usage_fraction(self):
        zone = SmartZone(SmartZoneConfig())
        frac = zone.usage_fraction(40_000)
        assert frac == 0.5  # 40K / 80K

    def test_should_compress_false_under_budget(self):
        zone = SmartZone(SmartZoneConfig())
        assert not zone.should_compress(50_000, 10_000)  # 60K < 80K

    def test_should_compress_true_over_budget(self):
        zone = SmartZone(SmartZoneConfig())
        assert zone.should_compress(70_000, 15_000)  # 85K > 80K

    def test_compression_aggressiveness_lossless(self):
        zone = SmartZone(SmartZoneConfig())
        level = zone.compression_aggressiveness(40_000)  # 50% of Smart Zone
        assert level == CompressionLevel.LOSSLESS

    def test_compression_aggressiveness_light_lossy(self):
        zone = SmartZone(SmartZoneConfig())
        level = zone.compression_aggressiveness(64_000)  # 80% of Smart Zone
        assert level == CompressionLevel.LIGHT_LOSSY

    def test_compression_aggressiveness_moderate(self):
        zone = SmartZone(SmartZoneConfig())
        level = zone.compression_aggressiveness(72_000)  # 90% of Smart Zone
        assert level == CompressionLevel.MODERATE_LOSSY

    def test_compression_aggressiveness_aggressive(self):
        zone = SmartZone(SmartZoneConfig())
        level = zone.compression_aggressiveness(90_000)  # >100% of Smart Zone
        assert level == CompressionLevel.AGGRESSIVE_LOSSY

    def test_smart_zone_pct(self):
        zone = SmartZone(SmartZoneConfig())
        assert zone.budget.smart_zone_pct == 40.0

    def test_tool_output_budget(self):
        zone = SmartZone(SmartZoneConfig())
        budget = zone.budget
        # 10% + 20% + 25% + 10% = 65% of Smart Zone
        expected = int(80_000 * 0.65)
        assert budget.tool_output_budget == expected
