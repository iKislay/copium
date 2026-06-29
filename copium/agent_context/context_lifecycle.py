"""Context lifecycle manager for agent sessions.

Orchestrates the full lifecycle of context in an agent session:
session start → tool calls → phase transitions → session end.

Coordinates between the phase detector, Smart Zone enforcer,
tool call classifier, and compression scheduler.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from copium.agent_context.phase_detector import (
    AgentPhase,
    PhaseDetector,
    PhaseDetectionResult,
    ToolCall,
)
from copium.agent_context.smart_zone import (
    CompressionLevel,
    SmartZone,
    SmartZoneConfig,
)
from copium.agent_context.tool_call_classifier import (
    ClassifiedToolCall,
    ToolCallClassifier,
)

logger = logging.getLogger(__name__)


@dataclass
class CompressionDecision:
    """Result of a compression decision for a single tool call."""

    should_compress: bool
    compression_level: CompressionLevel
    target_reduction: float  # 0.0 to 1.0 — how much to compress
    transforms: list[str]  # Names of transforms to apply
    reason: str
    phase: AgentPhase
    context_pressure: float  # 0.0 to 1.0 — how close to Smart Zone limit


@dataclass
class SessionState:
    """Tracked state for an agent session."""

    session_id: str
    start_time: float = field(default_factory=time.time)
    tool_calls: list[ToolCall] = field(default_factory=list)
    classified_calls: list[ClassifiedToolCall] = field(default_factory=list)
    current_phase: AgentPhase = AgentPhase.ORIENTATION
    phase_history: list[tuple[float, AgentPhase]] = field(default_factory=list)
    total_tokens_processed: int = 0
    total_tokens_saved: int = 0
    compression_decisions: list[CompressionDecision] = field(default_factory=list)

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    @property
    def savings_ratio(self) -> float:
        if self.total_tokens_processed == 0:
            return 0.0
        return self.total_tokens_saved / self.total_tokens_processed

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.start_time


class ContextLifecycleManager:
    """Manages the entire lifecycle of context in an agent session.

    Coordinates between phase detection, Smart Zone enforcement,
    tool classification, and compression scheduling to keep context
    usage below the quality degradation threshold.

    Example:
        >>> config = SmartZoneConfig(context_window=200000, model_family="claude-4")
        >>> manager = ContextLifecycleManager(config)
        >>> manager.on_session_start("session-123")
        >>> decision = manager.on_tool_call(
        ...     tool_name="list_dir",
        ...     arguments={"path": "/src"},
        ...     result_tokens=500,
        ... )
        >>> decision.should_compress
        False  # Not yet under pressure
    """

    def __init__(
        self,
        config: SmartZoneConfig | None = None,
        phase_detector: PhaseDetector | None = None,
        classifier: ToolCallClassifier | None = None,
    ):
        """Initialize lifecycle manager.

        Args:
            config: Smart Zone configuration. Defaults to standard cloud config.
            phase_detector: Custom phase detector. Defaults to standard.
            classifier: Custom tool call classifier. Defaults to standard.
        """
        self._config = config or SmartZoneConfig()
        self._smart_zone = SmartZone(self._config)
        self._phase_detector = phase_detector or PhaseDetector()
        self._classifier = classifier or ToolCallClassifier()
        self._sessions: dict[str, SessionState] = {}

    @property
    def smart_zone(self) -> SmartZone:
        return self._smart_zone

    def on_session_start(self, session_id: str) -> None:
        """Initialize a new agent session.

        Args:
            session_id: Unique session identifier.
        """
        state = SessionState(session_id=session_id)
        state.phase_history.append((time.time(), AgentPhase.ORIENTATION))
        self._sessions[session_id] = state
        logger.info(
            "Agent context session started: %s (Smart Zone: %d tokens)",
            session_id,
            self._smart_zone.budget.smart_zone_tokens,
        )

    def on_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        result_tokens: int = 0,
        current_context_tokens: int = 0,
        session_id: str | None = None,
    ) -> CompressionDecision:
        """Process a tool call and decide on compression.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool call arguments.
            result_tokens: Token count of the tool result.
            current_context_tokens: Current total context token count.
            session_id: Session ID. Uses first active session if None.

        Returns:
            CompressionDecision indicating if/how to compress the result.
        """
        state = self._get_session(session_id)
        arguments = arguments or {}

        # Record tool call
        tool_call = ToolCall(
            name=tool_name,
            arguments=arguments,
            result_tokens=result_tokens,
            timestamp=time.time(),
        )
        state.tool_calls.append(tool_call)

        # Classify the tool call
        classified = self._classifier.classify(tool_name, arguments, result_tokens)
        state.classified_calls.append(classified)

        # Detect current phase
        phase_result = self._phase_detector.detect(
            state.tool_calls,
            self._smart_zone.usage_fraction(current_context_tokens),
        )

        # Handle phase transition
        if phase_result.phase != state.current_phase:
            self._handle_phase_transition(state, phase_result)

        # Determine compression decision
        decision = self._make_compression_decision(
            state, classified, current_context_tokens, result_tokens
        )

        # Track metrics
        state.total_tokens_processed += result_tokens
        if decision.should_compress:
            state.total_tokens_saved += int(result_tokens * decision.target_reduction)
        state.compression_decisions.append(decision)

        return decision

    def on_session_end(self, session_id: str | None = None) -> dict[str, Any]:
        """End a session and return final metrics.

        Args:
            session_id: Session to end. Uses first active if None.

        Returns:
            Dict with session metrics (tokens processed, saved, phases, etc.).
        """
        state = self._get_session(session_id)
        metrics = {
            "session_id": state.session_id,
            "duration_seconds": state.duration_seconds,
            "tool_call_count": state.tool_call_count,
            "total_tokens_processed": state.total_tokens_processed,
            "total_tokens_saved": state.total_tokens_saved,
            "savings_ratio": state.savings_ratio,
            "final_phase": state.current_phase.value,
            "phase_transitions": len(state.phase_history),
            "compression_decisions_count": len(state.compression_decisions),
        }

        # Cleanup
        del self._sessions[state.session_id]
        logger.info(
            "Agent context session ended: %s (saved %d tokens, %.1f%% savings)",
            state.session_id,
            state.total_tokens_saved,
            state.savings_ratio * 100,
        )
        return metrics

    def get_session_state(self, session_id: str | None = None) -> SessionState:
        """Get current state of a session.

        Args:
            session_id: Session to query. Uses first active if None.

        Returns:
            Current SessionState.
        """
        return self._get_session(session_id)

    def _get_session(self, session_id: str | None) -> SessionState:
        """Resolve session by ID or get first active."""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        if self._sessions:
            return next(iter(self._sessions.values()))
        raise ValueError("No active sessions. Call on_session_start() first.")

    def _handle_phase_transition(
        self, state: SessionState, phase_result: PhaseDetectionResult
    ) -> None:
        """Handle a phase transition."""
        old_phase = state.current_phase
        new_phase = phase_result.phase
        state.current_phase = new_phase
        state.phase_history.append((time.time(), new_phase))

        logger.info(
            "Phase transition: %s → %s (confidence: %.2f, tool calls: %d)",
            old_phase.value,
            new_phase.value,
            phase_result.confidence,
            state.tool_call_count,
        )

    def _make_compression_decision(
        self,
        state: SessionState,
        classified: ClassifiedToolCall,
        current_context_tokens: int,
        incoming_tokens: int,
    ) -> CompressionDecision:
        """Decide whether and how to compress a tool call result."""
        should_compress = self._smart_zone.should_compress(
            current_context_tokens, incoming_tokens
        )
        compression_level = self._smart_zone.compression_aggressiveness(
            current_context_tokens
        )
        context_pressure = self._smart_zone.usage_fraction(current_context_tokens)

        # Determine target reduction based on compression level and content type
        if not should_compress and context_pressure < 0.5:
            # Under low pressure, only compress highly compressible content
            if classified.is_highly_compressible:
                should_compress = True
                target_reduction = 0.30
                transforms = self._get_light_transforms(state.current_phase)
                reason = "Proactive compression of highly-compressible content"
            else:
                return CompressionDecision(
                    should_compress=False,
                    compression_level=CompressionLevel.NONE,
                    target_reduction=0.0,
                    transforms=[],
                    reason="Under Smart Zone budget, no compression needed",
                    phase=state.current_phase,
                    context_pressure=context_pressure,
                )
        else:
            target_reduction = self._calculate_target_reduction(
                compression_level, classified
            )
            transforms = self._get_transforms_for_level(
                compression_level, state.current_phase, classified
            )
            reason = (
                f"Smart Zone pressure at {context_pressure:.0%}, "
                f"applying {compression_level.value} compression"
            )

        return CompressionDecision(
            should_compress=should_compress,
            compression_level=compression_level,
            target_reduction=target_reduction,
            transforms=transforms,
            reason=reason,
            phase=state.current_phase,
            context_pressure=context_pressure,
        )

    def _calculate_target_reduction(
        self,
        level: CompressionLevel,
        classified: ClassifiedToolCall,
    ) -> float:
        """Calculate target reduction based on level and content type."""
        base_reductions = {
            CompressionLevel.NONE: 0.0,
            CompressionLevel.LOSSLESS: 0.20,
            CompressionLevel.LIGHT_LOSSY: 0.40,
            CompressionLevel.MODERATE_LOSSY: 0.60,
            CompressionLevel.AGGRESSIVE_LOSSY: 0.80,
        }
        base = base_reductions.get(level, 0.0)
        # Scale by content compressibility
        return min(0.95, base * classified.compressibility / 0.5)

    def _get_light_transforms(self, phase: AgentPhase) -> list[str]:
        """Get lightweight transforms for proactive compression."""
        return ["session_dedup", "smart_crusher"]

    def _get_transforms_for_level(
        self,
        level: CompressionLevel,
        phase: AgentPhase,
        classified: ClassifiedToolCall,
    ) -> list[str]:
        """Get appropriate transforms for the given compression level and phase."""
        # Phase-based pipeline selection
        phase_transforms: dict[AgentPhase, list[str]] = {
            AgentPhase.ORIENTATION: [
                "smart_crusher",
                "session_dedup",
                "differential_response",
            ],
            AgentPhase.EXPLORATION: [
                "content_router",
                "session_dedup",
                "error_compressor",
            ],
            AgentPhase.IMPLEMENTATION: [
                "session_dedup",
                "error_compressor",
                "schema_compressor",
            ],
            AgentPhase.VERIFICATION: [
                "differential_response",
                "smart_crusher",
                "error_compressor",
            ],
            AgentPhase.UNKNOWN: ["session_dedup", "smart_crusher"],
        }

        transforms = list(phase_transforms.get(phase, ["session_dedup"]))

        # Add more aggressive transforms at higher levels
        if level in (CompressionLevel.MODERATE_LOSSY, CompressionLevel.AGGRESSIVE_LOSSY):
            if "smart_crusher" not in transforms:
                transforms.append("smart_crusher")
            if "output_compressor" not in transforms:
                transforms.append("output_compressor")

        return transforms
