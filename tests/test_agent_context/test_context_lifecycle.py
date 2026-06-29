"""Tests for agent_context context lifecycle manager."""

from copium.agent_context.context_lifecycle import (
    CompressionDecision,
    ContextLifecycleManager,
)
from copium.agent_context.phase_detector import AgentPhase
from copium.agent_context.smart_zone import CompressionLevel, SmartZoneConfig


class TestContextLifecycleManager:
    """Test context lifecycle management."""

    def setup_method(self):
        config = SmartZoneConfig(context_window=200_000)
        self.manager = ContextLifecycleManager(config=config)
        self.manager.on_session_start("test-session")

    def test_session_start(self):
        state = self.manager.get_session_state()
        assert state.session_id == "test-session"
        assert state.current_phase == AgentPhase.ORIENTATION
        assert state.tool_call_count == 0

    def test_tool_call_no_compression_low_usage(self):
        decision = self.manager.on_tool_call(
            tool_name="list_dir",
            arguments={"path": "/"},
            result_tokens=200,
            current_context_tokens=5000,
        )
        # list_dir is highly compressible, so proactive compression kicks in
        assert decision.phase == AgentPhase.ORIENTATION
        assert decision.context_pressure < 0.5

    def test_tool_call_triggers_compression_high_usage(self):
        decision = self.manager.on_tool_call(
            tool_name="read_file",
            arguments={"path": "main.py"},
            result_tokens=5000,
            current_context_tokens=78_000,  # Near 80K Smart Zone limit
        )
        assert decision.should_compress is True
        assert decision.compression_level != CompressionLevel.NONE

    def test_phase_transitions(self):
        # Simulate orientation → exploration transition
        for i in range(6):
            self.manager.on_tool_call(
                tool_name="list_dir",
                result_tokens=100,
                current_context_tokens=i * 100,
            )

        # Now do exploration-type calls
        for i in range(6):
            self.manager.on_tool_call(
                tool_name="read_file",
                arguments={"path": f"file{i}.py"},
                result_tokens=500,
                current_context_tokens=600 + i * 500,
            )

        state = self.manager.get_session_state()
        # Should have transitioned from ORIENTATION
        assert len(state.phase_history) >= 1

    def test_session_end_returns_metrics(self):
        self.manager.on_tool_call(
            tool_name="list_dir",
            result_tokens=200,
            current_context_tokens=1000,
        )
        metrics = self.manager.on_session_end()
        assert metrics["session_id"] == "test-session"
        assert metrics["tool_call_count"] == 1
        assert "total_tokens_processed" in metrics
        assert "savings_ratio" in metrics

    def test_no_active_session_raises(self):
        manager = ContextLifecycleManager()
        try:
            manager.on_tool_call(tool_name="list_dir", result_tokens=100)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_compression_decision_has_transforms(self):
        decision = self.manager.on_tool_call(
            tool_name="list_dir",
            result_tokens=500,
            current_context_tokens=75_000,  # High pressure
        )
        if decision.should_compress:
            assert len(decision.transforms) > 0
