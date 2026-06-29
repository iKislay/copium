"""Phase detection for agent sessions.

Detects the current phase of an agent session based on tool call patterns
and context usage, enabling phase-appropriate compression strategies.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentPhase(Enum):
    """Agent session lifecycle phases."""

    ORIENTATION = "orientation"
    EXPLORATION = "exploration"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    UNKNOWN = "unknown"


# Tool call categories for phase detection heuristics
_ORIENTATION_TOOLS = frozenset({
    "list_dir", "list_directory", "ls", "tree", "find",
    "grep", "grep_search", "rg", "ripgrep",
    "glob", "file_search",
    "get_workspace_structure",
})

_EXPLORATION_TOOLS = frozenset({
    "read_file", "cat", "head", "tail",
    "grep", "grep_search", "rg",
    "semantic_search", "search",
    "get_definitions", "get_references",
    "view_source",
})

_IMPLEMENTATION_TOOLS = frozenset({
    "write_file", "create_file", "edit_file",
    "replace_string_in_file", "insert_text",
    "run_command", "bash", "terminal",
    "run_in_terminal",
})

_VERIFICATION_TOOLS = frozenset({
    "run_tests", "test", "pytest", "jest",
    "lint", "eslint", "ruff", "mypy",
    "git_status", "git_diff", "diff",
    "check", "build", "compile",
})


@dataclass
class ToolCall:
    """Representation of a single tool call in an agent session."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result_tokens: int = 0
    timestamp: float = 0.0


@dataclass
class PhaseDetectionResult:
    """Result of phase detection with confidence score."""

    phase: AgentPhase
    confidence: float  # 0.0 to 1.0
    tool_call_count: int
    dominant_category: str
    transition_hint: str | None = None


class PhaseDetector:
    """Detects agent session phase from tool call patterns.

    Uses heuristic analysis of tool call sequences to determine which
    phase the agent is currently in. This enables the compression scheduler
    to apply phase-appropriate strategies.
    """

    def __init__(
        self,
        orientation_threshold: int = 5,
        exploration_threshold: int = 15,
        implementation_threshold: int = 30,
    ):
        """Initialize phase detector.

        Args:
            orientation_threshold: Max tool calls for orientation phase.
            exploration_threshold: Max tool calls for exploration phase.
            implementation_threshold: Max tool calls for implementation phase.
        """
        self._orientation_threshold = orientation_threshold
        self._exploration_threshold = exploration_threshold
        self._implementation_threshold = implementation_threshold

    def detect(
        self,
        tool_calls: list[ToolCall],
        context_usage: float = 0.0,
    ) -> PhaseDetectionResult:
        """Detect agent phase from tool call history.

        Uses both sequential position and tool type distribution to
        determine the current phase.

        Args:
            tool_calls: History of tool calls in this session.
            context_usage: Current context usage as fraction (0.0-1.0).

        Returns:
            PhaseDetectionResult with phase, confidence, and metadata.
        """
        if not tool_calls:
            return PhaseDetectionResult(
                phase=AgentPhase.ORIENTATION,
                confidence=0.5,
                tool_call_count=0,
                dominant_category="none",
                transition_hint="Session just started",
            )

        n = len(tool_calls)
        # Analyze recent tool calls (last 5) for phase signal
        recent = tool_calls[-min(5, n):]
        recent_names = [tc.name for tc in recent]
        category_counts = self._categorize_tools(recent_names)

        # Determine phase from heuristics
        phase, confidence, dominant = self._classify_phase(
            n, category_counts, context_usage
        )

        # Check for phase transition signals
        transition_hint = self._detect_transition(tool_calls, phase)

        return PhaseDetectionResult(
            phase=phase,
            confidence=confidence,
            tool_call_count=n,
            dominant_category=dominant,
            transition_hint=transition_hint,
        )

    def detect_from_headers(self, headers: dict[str, str]) -> AgentPhase | None:
        """Detect phase from explicit agent headers.

        Some agents send phase hints via HTTP headers:
        - X-Copium-Phase: orientation|exploration|implementation|verification
        - X-Agent-Phase: (same values)

        Args:
            headers: HTTP request headers (case-insensitive keys).

        Returns:
            AgentPhase if header found, None otherwise.
        """
        for header_name in ("x-copium-phase", "x-agent-phase"):
            value = headers.get(header_name, "").lower().strip()
            if value:
                try:
                    return AgentPhase(value)
                except ValueError:
                    logger.debug("Unknown phase header value: %s", value)
        return None

    def _categorize_tools(self, tool_names: list[str]) -> Counter:
        """Categorize tool names into phase categories."""
        counts: Counter = Counter()
        for name in tool_names:
            name_lower = name.lower()
            if name_lower in _ORIENTATION_TOOLS:
                counts["orientation"] += 1
            elif name_lower in _IMPLEMENTATION_TOOLS:
                counts["implementation"] += 1
            elif name_lower in _VERIFICATION_TOOLS:
                counts["verification"] += 1
            elif name_lower in _EXPLORATION_TOOLS:
                counts["exploration"] += 1
            else:
                counts["unknown"] += 1
        return counts

    def _classify_phase(
        self,
        tool_call_count: int,
        category_counts: Counter,
        context_usage: float,
    ) -> tuple[AgentPhase, float, str]:
        """Classify phase from tool count and category distribution.

        Returns:
            (phase, confidence, dominant_category)
        """
        total = sum(category_counts.values()) or 1
        dominant = category_counts.most_common(1)[0][0] if category_counts else "unknown"
        dominant_ratio = category_counts.get(dominant, 0) / total

        # Position-based heuristic (tool call count)
        if tool_call_count <= self._orientation_threshold:
            position_phase = AgentPhase.ORIENTATION
        elif tool_call_count <= self._exploration_threshold:
            position_phase = AgentPhase.EXPLORATION
        elif tool_call_count <= self._implementation_threshold:
            position_phase = AgentPhase.IMPLEMENTATION
        else:
            position_phase = AgentPhase.VERIFICATION

        # Content-based heuristic (tool type distribution)
        content_phase_map = {
            "orientation": AgentPhase.ORIENTATION,
            "exploration": AgentPhase.EXPLORATION,
            "implementation": AgentPhase.IMPLEMENTATION,
            "verification": AgentPhase.VERIFICATION,
        }
        content_phase = content_phase_map.get(dominant, AgentPhase.UNKNOWN)

        # Combine: prefer content signal if strong, else use position
        if dominant_ratio >= 0.7 and content_phase != AgentPhase.UNKNOWN:
            phase = content_phase
            confidence = min(0.95, dominant_ratio)
        elif position_phase == content_phase:
            phase = position_phase
            confidence = 0.85
        else:
            # Conflict — use position as tiebreaker but lower confidence
            phase = position_phase
            confidence = 0.6

        return phase, confidence, dominant

    def _detect_transition(
        self,
        tool_calls: list[ToolCall],
        current_phase: AgentPhase,
    ) -> str | None:
        """Detect if the agent is about to transition phases."""
        if len(tool_calls) < 3:
            return None

        last_three = [tc.name.lower() for tc in tool_calls[-3:]]

        # Orientation → Exploration: first non-structural read
        if current_phase == AgentPhase.ORIENTATION:
            if any(t in _EXPLORATION_TOOLS - _ORIENTATION_TOOLS for t in last_three):
                return "Transitioning to exploration"

        # Exploration → Implementation: first write/edit
        if current_phase == AgentPhase.EXPLORATION:
            if any(t in _IMPLEMENTATION_TOOLS for t in last_three):
                return "Transitioning to implementation"

        # Implementation → Verification: first test/lint run
        if current_phase == AgentPhase.IMPLEMENTATION:
            if any(t in _VERIFICATION_TOOLS for t in last_three):
                return "Transitioning to verification"

        return None
