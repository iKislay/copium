"""Tests for agent_context phase detector."""

from copium.agent_context.phase_detector import (
    AgentPhase,
    PhaseDetector,
    ToolCall,
)


class TestPhaseDetector:
    """Test phase detection from tool call patterns."""

    def setup_method(self):
        self.detector = PhaseDetector()

    def test_empty_session_returns_orientation(self):
        result = self.detector.detect([])
        assert result.phase == AgentPhase.ORIENTATION
        assert result.tool_call_count == 0

    def test_orientation_phase_from_structural_tools(self):
        tool_calls = [
            ToolCall(name="list_dir", arguments={"path": "/"}),
            ToolCall(name="list_dir", arguments={"path": "/src"}),
            ToolCall(name="grep_search", arguments={"query": "main"}),
            ToolCall(name="file_search", arguments={"query": "*.py"}),
        ]
        result = self.detector.detect(tool_calls)
        assert result.phase == AgentPhase.ORIENTATION
        assert result.confidence >= 0.6

    def test_exploration_phase_from_reads(self):
        tool_calls = [
            ToolCall(name="list_dir"),
            ToolCall(name="list_dir"),
            ToolCall(name="list_dir"),
            ToolCall(name="list_dir"),
            ToolCall(name="list_dir"),
            ToolCall(name="read_file"),
            ToolCall(name="read_file"),
            ToolCall(name="semantic_search"),
            ToolCall(name="read_file"),
            ToolCall(name="read_file"),
        ]
        result = self.detector.detect(tool_calls)
        assert result.phase == AgentPhase.EXPLORATION

    def test_implementation_phase_from_writes(self):
        tool_calls = [ToolCall(name="list_dir")] * 5
        tool_calls += [ToolCall(name="read_file")] * 10
        tool_calls += [
            ToolCall(name="write_file"),
            ToolCall(name="edit_file"),
            ToolCall(name="write_file"),
            ToolCall(name="run_in_terminal"),
            ToolCall(name="write_file"),
        ]
        result = self.detector.detect(tool_calls)
        assert result.phase == AgentPhase.IMPLEMENTATION

    def test_verification_phase_from_test_tools(self):
        tool_calls = [ToolCall(name="list_dir")] * 5
        tool_calls += [ToolCall(name="read_file")] * 10
        tool_calls += [ToolCall(name="write_file")] * 15
        tool_calls += [
            ToolCall(name="run_tests"),
            ToolCall(name="lint"),
            ToolCall(name="git_diff"),
            ToolCall(name="run_tests"),
            ToolCall(name="git_status"),
        ]
        result = self.detector.detect(tool_calls)
        assert result.phase == AgentPhase.VERIFICATION

    def test_detect_from_headers(self):
        headers = {"x-copium-phase": "implementation"}
        phase = self.detector.detect_from_headers(headers)
        assert phase == AgentPhase.IMPLEMENTATION

    def test_detect_from_headers_unknown_value(self):
        headers = {"x-copium-phase": "invalid_phase"}
        phase = self.detector.detect_from_headers(headers)
        assert phase is None

    def test_detect_from_headers_empty(self):
        phase = self.detector.detect_from_headers({})
        assert phase is None

    def test_transition_hint_orientation_to_exploration(self):
        tool_calls = [
            ToolCall(name="list_dir"),
            ToolCall(name="list_dir"),
            ToolCall(name="semantic_search"),
        ]
        result = self.detector.detect(tool_calls)
        assert result.transition_hint is not None
        assert "exploration" in result.transition_hint.lower()

    def test_custom_thresholds(self):
        detector = PhaseDetector(
            orientation_threshold=2,
            exploration_threshold=5,
            implementation_threshold=10,
        )
        tool_calls = [ToolCall(name="read_file")] * 3
        result = detector.detect(tool_calls)
        assert result.phase == AgentPhase.EXPLORATION