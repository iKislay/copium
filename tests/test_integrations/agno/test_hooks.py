"""Tests for Agno hooks integration.

Tests cover:
1. CopiumPreHook - Pre-hook for tracking before LLM calls
2. CopiumPostHook - Post-hook for tracking after LLM calls
3. create_copium_hooks - Convenience function
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Check if Agno is available
try:
    import agno  # noqa: F401

    AGNO_AVAILABLE = True
except ImportError:
    AGNO_AVAILABLE = False

from copium import CopiumConfig, CopiumMode

# Skip all tests if Agno not installed
pytestmark = pytest.mark.skipif(not AGNO_AVAILABLE, reason="Agno not installed")


class TestCopiumPreHook:
    """Tests for CopiumPreHook."""

    def test_init_defaults(self):
        """Initialize with default settings."""
        from copium.integrations.agno import CopiumPreHook

        hook = CopiumPreHook()

        assert hook.mode == CopiumMode.OPTIMIZE
        assert hook.model == "gpt-4o"
        assert hook.total_tokens_saved == 0
        assert hook.metrics_history == []

    def test_init_with_custom_config(self):
        """Initialize with custom config."""
        from copium.integrations.agno import CopiumPreHook

        config = CopiumConfig(default_mode=CopiumMode.AUDIT)
        hook = CopiumPreHook(
            config=config,
            mode=CopiumMode.SIMULATE,
            model="claude-3-5-sonnet-20241022",
        )

        assert hook.config is config
        assert hook.mode == CopiumMode.SIMULATE
        assert hook.model == "claude-3-5-sonnet-20241022"

    def test_call_returns_input_unchanged(self):
        """Hook returns input unchanged (optimization at model level)."""
        from copium.integrations.agno import CopiumPreHook

        hook = CopiumPreHook()

        run_input = "Hello, how are you?"
        result = hook(run_input)

        assert result == run_input

    def test_call_tracks_metrics(self):
        """Hook tracks metrics on each call."""
        from copium.integrations.agno import CopiumPreHook

        hook = CopiumPreHook()

        hook("First input")
        hook("Second input")

        assert len(hook.metrics_history) == 2
        assert all(m.request_id for m in hook.metrics_history)
        assert all(isinstance(m.timestamp, datetime) for m in hook.metrics_history)

    def test_metrics_history_limited(self):
        """Metrics history is limited to 100 entries."""
        from copium.integrations.agno import CopiumPreHook

        hook = CopiumPreHook()

        # Call 150 times
        for i in range(150):
            hook(f"Input {i}")

        assert len(hook.metrics_history) == 100

    def test_get_savings_summary_empty(self):
        """get_savings_summary with no history."""
        from copium.integrations.agno import CopiumPreHook

        hook = CopiumPreHook()
        summary = hook.get_savings_summary()

        assert summary["total_requests"] == 0
        assert summary["total_tokens_saved"] == 0
        assert summary["average_savings_percent"] == 0

    def test_get_savings_summary_with_data(self):
        """get_savings_summary with metrics."""
        from copium.integrations.agno import CopiumPreHook

        hook = CopiumPreHook()

        # Make some calls
        hook("Input 1")
        hook("Input 2")

        summary = hook.get_savings_summary()

        assert summary["total_requests"] == 2
        # Pre-hook doesn't do actual optimization, so tokens_saved is 0
        assert summary["total_tokens_saved"] == 0


class TestCopiumPostHook:
    """Tests for CopiumPostHook."""

    def test_init_defaults(self):
        """Initialize with default settings."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()

        assert hook.log_level == "INFO"
        assert hook.token_alert_threshold is None
        assert hook.total_requests == 0
        assert hook.alerts == []

    def test_init_with_threshold(self):
        """Initialize with alert threshold."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook(
            log_level="DEBUG",
            token_alert_threshold=10000,
        )

        assert hook.log_level == "DEBUG"
        assert hook.token_alert_threshold == 10000

    def test_call_returns_output_unchanged(self):
        """Hook returns output unchanged."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()

        output = MagicMock()
        output.content = "Hello!"
        result = hook(output)

        assert result is output

    def test_call_tracks_requests(self):
        """Hook tracks requests on each call."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()

        output1 = MagicMock()
        output1.content = "First response"
        output2 = MagicMock()
        output2.content = "Second response"

        hook(output1)
        hook(output2)

        assert hook.total_requests == 2

    def test_call_extracts_token_metrics(self):
        """Hook extracts token metrics from response."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()

        output = MagicMock()
        output.content = "Response"
        output.metrics = MagicMock()
        output.metrics.input_tokens = 50
        output.metrics.output_tokens = 20
        output.metrics.total_tokens = 70

        hook(output)

        assert hook._requests[0]["input_tokens"] == 50
        assert hook._requests[0]["output_tokens"] == 20
        assert hook._requests[0]["total_tokens"] == 70

    def test_call_triggers_alert(self):
        """Hook triggers alert when threshold exceeded."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook(token_alert_threshold=50)

        output = MagicMock()
        output.content = "Response"
        output.metrics = MagicMock()
        output.metrics.total_tokens = 100  # Exceeds threshold

        hook(output)

        assert len(hook.alerts) == 1
        assert "Token alert" in hook.alerts[0]
        assert "100" in hook.alerts[0]

    def test_call_no_alert_below_threshold(self):
        """No alert when tokens below threshold."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook(token_alert_threshold=100)

        output = MagicMock()
        output.content = "Response"
        output.metrics = MagicMock()
        output.metrics.total_tokens = 50  # Below threshold

        hook(output)

        assert len(hook.alerts) == 0

    def test_requests_limited(self):
        """Request history is limited to 1000 entries."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()

        # Call 1500 times
        for i in range(1500):
            output = MagicMock()
            output.content = f"Response {i}"
            hook(output)

        assert len(hook._requests) == 1000

    def test_get_summary_empty(self):
        """get_summary with no requests."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()
        summary = hook.get_summary()

        assert summary["total_requests"] == 0
        assert summary["total_tokens"] == 0
        assert summary["alerts"] == 0

    def test_get_summary_with_data(self):
        """get_summary with requests."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()

        # Add some requests directly
        hook._requests = [
            {"total_tokens": 100},
            {"total_tokens": 200},
            {"total_tokens": 50},
        ]

        summary = hook.get_summary()

        assert summary["total_requests"] == 3
        assert summary["total_tokens"] == 350
        assert summary["average_tokens"] == 350 / 3

    def test_reset(self):
        """reset() clears all state."""
        from copium.integrations.agno import CopiumPostHook

        hook = CopiumPostHook()

        # Add some state
        hook._requests = [{"test": 1}]
        hook._alerts = ["alert"]

        hook.reset()

        assert hook._requests == []
        assert hook._alerts == []


class TestCreateCopiumHooks:
    """Tests for create_copium_hooks convenience function."""

    def test_returns_tuple(self):
        """Returns tuple of (pre_hook, post_hook)."""
        from copium.integrations.agno import (
            CopiumPostHook,
            CopiumPreHook,
            create_copium_hooks,
        )

        pre_hook, post_hook = create_copium_hooks()

        assert isinstance(pre_hook, CopiumPreHook)
        assert isinstance(post_hook, CopiumPostHook)

    def test_passes_config_to_pre_hook(self):
        """Passes config to pre_hook."""
        from copium.integrations.agno import create_copium_hooks

        config = CopiumConfig(default_mode=CopiumMode.AUDIT)
        pre_hook, _ = create_copium_hooks(config=config)

        assert pre_hook.config is config

    def test_passes_mode_to_pre_hook(self):
        """Passes mode to pre_hook."""
        from copium.integrations.agno import create_copium_hooks

        pre_hook, _ = create_copium_hooks(mode=CopiumMode.SIMULATE)

        assert pre_hook.mode == CopiumMode.SIMULATE

    def test_passes_model_to_pre_hook(self):
        """Passes model to pre_hook."""
        from copium.integrations.agno import create_copium_hooks

        pre_hook, _ = create_copium_hooks(model="claude-3-5-sonnet-20241022")

        assert pre_hook.model == "claude-3-5-sonnet-20241022"

    def test_passes_log_level_to_post_hook(self):
        """Passes log_level to post_hook."""
        from copium.integrations.agno import create_copium_hooks

        _, post_hook = create_copium_hooks(log_level="DEBUG")

        assert post_hook.log_level == "DEBUG"

    def test_passes_threshold_to_post_hook(self):
        """Passes token_alert_threshold to post_hook."""
        from copium.integrations.agno import create_copium_hooks

        _, post_hook = create_copium_hooks(token_alert_threshold=5000)

        assert post_hook.token_alert_threshold == 5000

    def test_all_parameters(self):
        """Test with all parameters."""
        from copium.integrations.agno import create_copium_hooks

        config = CopiumConfig()
        pre_hook, post_hook = create_copium_hooks(
            config=config,
            mode=CopiumMode.AUDIT,
            model="gpt-4-turbo",
            log_level="WARNING",
            token_alert_threshold=8000,
        )

        assert pre_hook.config is config
        assert pre_hook.mode == CopiumMode.AUDIT
        assert pre_hook.model == "gpt-4-turbo"
        assert post_hook.log_level == "WARNING"
        assert post_hook.token_alert_threshold == 8000
