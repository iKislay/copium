"""Tests for agent_context health monitor."""

from copium.agent_context.context_health import (
    ContextHealthMonitor,
    HealthReport,
)
from copium.agent_context.phase_detector import AgentPhase
from copium.agent_context.smart_zone import CompressionLevel


class TestContextHealthMonitor:
    """Test context health monitoring."""

    def setup_method(self):
        self.monitor = ContextHealthMonitor(
            smart_zone_tokens=80_000,
            total_context_tokens=200_000,
        )

    def test_initial_health_is_healthy(self):
        assert self.monitor.get_current_health() == "healthy"

    def test_record_snapshot(self):
        snapshot = self.monitor.record_snapshot(
            current_usage=20_000,
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.LOSSLESS,
            tool_call_count=3,
            tokens_saved=1000,
        )
        assert snapshot.usage_fraction == 0.25
        assert snapshot.phase == AgentPhase.ORIENTATION

    def test_warning_threshold(self):
        self.monitor.record_snapshot(
            current_usage=60_000,  # 75% of 80K
            phase=AgentPhase.EXPLORATION,
            compression_level=CompressionLevel.LIGHT_LOSSY,
            tool_call_count=10,
            tokens_saved=5000,
        )
        assert self.monitor.get_current_health() == "warning"

    def test_critical_threshold(self):
        self.monitor.record_snapshot(
            current_usage=75_000,  # 93.75% of 80K
            phase=AgentPhase.IMPLEMENTATION,
            compression_level=CompressionLevel.AGGRESSIVE_LOSSY,
            tool_call_count=20,
            tokens_saved=10000,
        )
        assert self.monitor.get_current_health() == "critical"

    def test_generate_report(self):
        self.monitor.record_snapshot(
            current_usage=30_000,
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.LOSSLESS,
            tool_call_count=5,
            tokens_saved=2000,
        )
        report = self.monitor.generate_report("test-session")
        assert report.session_id == "test-session"
        assert report.overall_health in ("healthy", "warning", "degraded", "critical")
        assert 0.0 <= report.health_score <= 1.0
        assert report.snapshots_count == 1

    def test_peak_usage_tracking(self):
        # Record increasing usage
        for usage in [10_000, 30_000, 50_000, 40_000, 20_000]:
            self.monitor.record_snapshot(
                current_usage=usage,
                phase=AgentPhase.EXPLORATION,
                compression_level=CompressionLevel.LOSSLESS,
                tool_call_count=5,
                tokens_saved=1000,
            )
        report = self.monitor.generate_report("test")
        assert report.peak_usage_fraction == 50_000 / 80_000

    def test_warnings_generated(self):
        self.monitor.record_snapshot(
            current_usage=75_000,  # Critical level
            phase=AgentPhase.IMPLEMENTATION,
            compression_level=CompressionLevel.AGGRESSIVE_LOSSY,
            tool_call_count=20,
            tokens_saved=5000,
        )
        report = self.monitor.generate_report("test")
        assert len(report.warnings) > 0
        assert "CRITICAL" in report.warnings[0]

    def test_recommendations_generated(self):
        # Simulate high peak usage
        self.monitor.record_snapshot(
            current_usage=76_000,
            phase=AgentPhase.IMPLEMENTATION,
            compression_level=CompressionLevel.AGGRESSIVE_LOSSY,
            tool_call_count=25,
            tokens_saved=2000,
        )
        report = self.monitor.generate_report("test")
        assert len(report.recommendations) > 0
