"""Tests for compression modes and observability dashboard."""

from __future__ import annotations

import pytest

from copium.compression.modes import (
    CompressionModeDispatcher,
    ContentClassification,
    Mode,
    ModeConfig,
    ModeResult,
)
from copium.observability.dashboard import (
    CompressionDashboard,
    CompressionDiff,
    CostEstimate,
    DiffSegment,
    SectionMetrics,
    SessionBudget,
)


# =============================================================================
# Compression Modes Tests
# =============================================================================


class TestCompressionModeDispatcher:
    """Tests for CompressionModeDispatcher."""

    def setup_method(self):
        self.dispatcher = CompressionModeDispatcher()

    def test_lossless_preserves_content(self):
        """Lossless mode should normalize but keep essential content."""
        code = "def hello():\n    return 'world'\n"
        result = self.dispatcher.compress(code, mode_override=Mode.LOSSLESS)
        assert result.mode == Mode.LOSSLESS
        assert result.is_reversible
        assert result.retrieval_key is not None
        assert "def hello" in result.compressed
        assert "return" in result.compressed

    def test_lossy_reduces_tokens(self):
        """Lossy mode should reduce token count."""
        code = """# This is a long comment about what the function does
# It goes on for several lines
# And includes lots of detail
def process():
    # Another comment here
    x = 1
    return x
"""
        config = ModeConfig(mode=Mode.LOSSY, lossy_aggressiveness=0.8)
        dispatcher = CompressionModeDispatcher(config)
        result = dispatcher.compress(code)
        assert result.mode == Mode.LOSSY
        assert not result.is_reversible
        assert result.tokens_after <= result.tokens_before

    def test_hybrid_preserves_code(self):
        """Hybrid mode should keep code but compress comments."""
        code = """# This is a comment that can be removed
def important_function():
    # Another removable comment
    return 42
"""
        config = ModeConfig(mode=Mode.HYBRID, lossy_aggressiveness=0.8)
        dispatcher = CompressionModeDispatcher(config)
        result = dispatcher.compress(code)
        assert result.mode == Mode.HYBRID
        assert "def important_function" in result.compressed
        assert "return 42" in result.compressed

    def test_archive_minimal_output(self):
        """Archive mode should produce minimal inline content."""
        code = "def long_function():\n" + "    x = 1\n" * 50
        result = self.dispatcher.compress(code, mode_override=Mode.ARCHIVE)
        assert result.mode == Mode.ARCHIVE
        assert result.is_reversible
        assert result.retrieval_key is not None
        assert result.tokens_after < result.tokens_before
        assert "[archived:" in result.compressed

    def test_mode_selection_with_classification(self):
        """Hybrid mode should route code and comments differently."""
        code_content = "def compute():\n    return 1 + 2"
        comment_content = "# This is just a comment\n# Another comment"

        config = ModeConfig(mode=Mode.HYBRID)
        dispatcher = CompressionModeDispatcher(config)

        code_result = dispatcher.compress(
            code_content,
            classification=ContentClassification(content_type="code", is_executable=True),
        )
        comment_result = dispatcher.compress(
            comment_content,
            classification=ContentClassification(content_type="comment"),
        )

        # Code should get lossless treatment
        assert "def compute" in code_result.compressed

    def test_empty_content(self):
        """Empty content should pass through."""
        result = self.dispatcher.compress("")
        assert result.compressed == ""
        assert result.tokens_saved == 0

    def test_duration_tracked(self):
        """Duration should be tracked."""
        result = self.dispatcher.compress("def f(): pass")
        assert result.duration_ms >= 0


# =============================================================================
# Dashboard Tests
# =============================================================================


class TestCompressionDashboard:
    """Tests for CompressionDashboard."""

    def setup_method(self):
        self.dashboard = CompressionDashboard(max_tokens=100000)

    def test_record_compression(self):
        metrics = self.dashboard.record_compression(
            name="test_section",
            content_type="code",
            original_tokens=1000,
            compressed_tokens=600,
            mode="hybrid",
            preservation_score=0.95,
        )
        assert metrics.tokens_saved == 400
        assert metrics.savings_pct == 40.0
        assert self.dashboard.total_tokens_saved == 400

    def test_multiple_sections(self):
        self.dashboard.record_compression(
            name="section_1",
            content_type="code",
            original_tokens=500,
            compressed_tokens=300,
        )
        self.dashboard.record_compression(
            name="section_2",
            content_type="comment",
            original_tokens=300,
            compressed_tokens=50,
        )
        assert self.dashboard.total_tokens_saved == 450
        assert len(self.dashboard.sections) == 2

    def test_budget_tracking(self):
        self.dashboard.update_budget(
            system_prompt_tokens=2000,
            history_tokens=5000,
            tool_tokens=3000,
            current_turn_tokens=1000,
        )
        budget = self.dashboard.budget
        assert budget.used_tokens == 11000
        assert budget.available_tokens == 89000
        assert not budget.is_near_limit()

    def test_near_limit_detection(self):
        self.dashboard.update_budget(
            system_prompt_tokens=50000,
            history_tokens=30000,
            tool_tokens=10000,
            current_turn_tokens=5000,
        )
        assert self.dashboard.budget.is_near_limit(threshold=0.9)

    def test_cost_estimation(self):
        self.dashboard.record_compression(
            name="big_section",
            content_type="code",
            original_tokens=10000,
            compressed_tokens=4000,
        )
        cost = self.dashboard.estimate_cost_savings()
        assert cost.input_tokens == 6000
        assert cost.input_cost > 0
        assert cost.total_cost > 0

    def test_average_compression_ratio(self):
        self.dashboard.record_compression(
            name="s1", content_type="code",
            original_tokens=100, compressed_tokens=50,
        )
        self.dashboard.record_compression(
            name="s2", content_type="code",
            original_tokens=100, compressed_tokens=50,
        )
        assert self.dashboard.average_compression_ratio == 0.5

    def test_render_summary(self):
        self.dashboard.record_compression(
            name="test", content_type="code",
            original_tokens=1000, compressed_tokens=500,
        )
        summary = self.dashboard.render_summary()
        assert "Copium" in summary
        assert "500" in summary  # tokens saved

    def test_generate_diff(self):
        original = "line1\nline2\nline3\nline4"
        compressed = "line1\nline3"  # line2 and line4 removed
        diff = self.dashboard.generate_diff(original, compressed)
        assert isinstance(diff, CompressionDiff)
        assert diff.kept_tokens > 0
        assert diff.removed_tokens > 0

    def test_empty_dashboard(self):
        assert self.dashboard.total_tokens_saved == 0
        assert self.dashboard.average_compression_ratio == 1.0
        assert self.dashboard.average_preservation_score == 1.0


class TestSessionBudget:
    """Tests for SessionBudget."""

    def test_defaults(self):
        budget = SessionBudget()
        assert budget.max_tokens == 128000
        assert budget.available_tokens == 128000
        assert budget.usage_pct == 0.0

    def test_usage_calculation(self):
        budget = SessionBudget(max_tokens=100000, used_tokens=75000)
        assert budget.available_tokens == 25000
        assert budget.usage_pct == 75.0
        assert not budget.is_near_limit()

    def test_near_limit(self):
        budget = SessionBudget(max_tokens=100000, used_tokens=95000)
        assert budget.is_near_limit(threshold=0.9)


class TestCostEstimate:
    """Tests for CostEstimate."""

    def test_cost_calculation(self):
        cost = CostEstimate(
            input_tokens=1_000_000,
            output_tokens=100_000,
            input_cost_per_mtok=3.0,
            output_cost_per_mtok=15.0,
        )
        assert cost.input_cost == 3.0
        assert cost.output_cost == 1.5
        assert cost.total_cost == 4.5

    def test_zero_tokens(self):
        cost = CostEstimate()
        assert cost.total_cost == 0.0
