"""Context health monitoring for agent sessions.

Provides real-time metrics on context quality, Smart Zone utilization,
and compression effectiveness. Enables dashboards and alerting when
context quality degrades.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from copium.agent_context.phase_detector import AgentPhase
from copium.agent_context.smart_zone import CompressionLevel

logger = logging.getLogger(__name__)


@dataclass
class ContextSnapshot:
    """Point-in-time snapshot of context health metrics."""

    timestamp: float
    total_tokens: int
    smart_zone_tokens: int
    current_usage: int
    usage_fraction: float  # current / smart_zone
    phase: AgentPhase
    compression_level: CompressionLevel
    tool_call_count: int
    tokens_saved_cumulative: int
    savings_ratio: float


@dataclass
class PhaseMetrics:
    """Aggregated metrics for a single phase."""

    phase: AgentPhase
    duration_seconds: float = 0.0
    tool_calls: int = 0
    tokens_consumed: int = 0
    tokens_saved: int = 0
    compression_decisions: int = 0
    avg_compression_ratio: float = 0.0


@dataclass
class HealthReport:
    """Complete health report for a session."""

    session_id: str
    duration_seconds: float
    overall_health: str  # "healthy", "warning", "degraded", "critical"
    health_score: float  # 0.0 to 1.0
    smart_zone_utilization: float
    peak_usage_fraction: float
    total_tokens_processed: int
    total_tokens_saved: int
    overall_savings_ratio: float
    phase_metrics: dict[str, PhaseMetrics]
    snapshots_count: int
    warnings: list[str]
    recommendations: list[str]


class ContextHealthMonitor:
    """Monitors context health metrics in real-time.

    Tracks Smart Zone utilization, compression effectiveness, and
    phase distribution to provide actionable health reports.

    Example:
        >>> monitor = ContextHealthMonitor(smart_zone_tokens=80000)
        >>> monitor.record_snapshot(
        ...     current_usage=25000,
        ...     phase=AgentPhase.EXPLORATION,
        ...     compression_level=CompressionLevel.LOSSLESS,
        ...     tool_call_count=8,
        ...     tokens_saved=3000,
        ... )
        >>> report = monitor.generate_report("session-123")
        >>> report.overall_health
        'healthy'
    """

    def __init__(
        self,
        smart_zone_tokens: int = 80000,
        total_context_tokens: int = 200000,
        warning_threshold: float = 0.7,
        critical_threshold: float = 0.9,
    ):
        """Initialize health monitor.

        Args:
            smart_zone_tokens: Smart Zone budget in tokens.
            total_context_tokens: Total context window size.
            warning_threshold: Fraction of Smart Zone for warning state.
            critical_threshold: Fraction of Smart Zone for critical state.
        """
        self._smart_zone_tokens = smart_zone_tokens
        self._total_context_tokens = total_context_tokens
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._snapshots: list[ContextSnapshot] = []
        self._phase_starts: dict[AgentPhase, float] = {}
        self._phase_metrics: dict[AgentPhase, PhaseMetrics] = {}
        self._start_time = time.time()
        self._peak_usage: float = 0.0
        self._warnings: list[str] = []

    def record_snapshot(
        self,
        current_usage: int,
        phase: AgentPhase,
        compression_level: CompressionLevel,
        tool_call_count: int,
        tokens_saved: int,
    ) -> ContextSnapshot:
        """Record a point-in-time health snapshot.

        Args:
            current_usage: Current token count in context.
            phase: Current agent phase.
            compression_level: Current compression level being applied.
            tool_call_count: Total tool calls so far.
            tokens_saved: Cumulative tokens saved.

        Returns:
            The recorded snapshot.
        """
        usage_fraction = (
            current_usage / self._smart_zone_tokens
            if self._smart_zone_tokens > 0
            else 1.0
        )

        total_processed = current_usage + tokens_saved
        savings_ratio = tokens_saved / total_processed if total_processed > 0 else 0.0

        snapshot = ContextSnapshot(
            timestamp=time.time(),
            total_tokens=self._total_context_tokens,
            smart_zone_tokens=self._smart_zone_tokens,
            current_usage=current_usage,
            usage_fraction=usage_fraction,
            phase=phase,
            compression_level=compression_level,
            tool_call_count=tool_call_count,
            tokens_saved_cumulative=tokens_saved,
            savings_ratio=savings_ratio,
        )

        self._snapshots.append(snapshot)

        # Track peak
        if usage_fraction > self._peak_usage:
            self._peak_usage = usage_fraction

        # Check for warnings
        self._check_warnings(snapshot)

        # Update phase metrics
        self._update_phase_metrics(snapshot)

        return snapshot

    def generate_report(self, session_id: str) -> HealthReport:
        """Generate a complete health report.

        Args:
            session_id: Session identifier for the report.

        Returns:
            HealthReport with overall health, metrics, and recommendations.
        """
        duration = time.time() - self._start_time

        # Calculate overall health
        health_score, health_status = self._calculate_health()

        # Calculate overall metrics
        total_saved = (
            self._snapshots[-1].tokens_saved_cumulative if self._snapshots else 0
        )
        last_usage = self._snapshots[-1].current_usage if self._snapshots else 0
        total_processed = last_usage + total_saved
        savings_ratio = total_saved / total_processed if total_processed > 0 else 0.0
        utilization = last_usage / self._smart_zone_tokens if self._smart_zone_tokens else 0.0

        # Generate recommendations
        recommendations = self._generate_recommendations()

        return HealthReport(
            session_id=session_id,
            duration_seconds=duration,
            overall_health=health_status,
            health_score=health_score,
            smart_zone_utilization=utilization,
            peak_usage_fraction=self._peak_usage,
            total_tokens_processed=total_processed,
            total_tokens_saved=total_saved,
            overall_savings_ratio=savings_ratio,
            phase_metrics={
                p.value: m for p, m in self._phase_metrics.items()
            },
            snapshots_count=len(self._snapshots),
            warnings=self._warnings.copy(),
            recommendations=recommendations,
        )

    def get_current_health(self) -> str:
        """Quick health check — returns status string."""
        if not self._snapshots:
            return "healthy"
        last = self._snapshots[-1]
        if last.usage_fraction >= self._critical_threshold:
            return "critical"
        if last.usage_fraction >= self._warning_threshold:
            return "warning"
        if last.usage_fraction >= 0.5:
            return "degraded"
        return "healthy"

    def _check_warnings(self, snapshot: ContextSnapshot) -> None:
        """Check snapshot for warning conditions."""
        if snapshot.usage_fraction >= self._critical_threshold:
            self._warnings.append(
                f"CRITICAL: Context at {snapshot.usage_fraction:.0%} of Smart Zone "
                f"(tool call #{snapshot.tool_call_count})"
            )
        elif snapshot.usage_fraction >= self._warning_threshold:
            self._warnings.append(
                f"WARNING: Context at {snapshot.usage_fraction:.0%} of Smart Zone "
                f"(tool call #{snapshot.tool_call_count})"
            )

    def _update_phase_metrics(self, snapshot: ContextSnapshot) -> None:
        """Update per-phase metrics from snapshot."""
        phase = snapshot.phase
        if phase not in self._phase_metrics:
            self._phase_metrics[phase] = PhaseMetrics(phase=phase)
            self._phase_starts[phase] = snapshot.timestamp

        metrics = self._phase_metrics[phase]
        metrics.tool_calls = snapshot.tool_call_count
        metrics.duration_seconds = snapshot.timestamp - self._phase_starts[phase]

    def _calculate_health(self) -> tuple[float, str]:
        """Calculate overall health score and status."""
        if not self._snapshots:
            return 1.0, "healthy"

        # Health factors:
        # 1. Peak usage (lower is better)
        peak_factor = max(0.0, 1.0 - self._peak_usage)

        # 2. Savings ratio (higher is better when under pressure)
        last = self._snapshots[-1]
        savings_factor = min(1.0, last.savings_ratio * 2)  # 50% savings = 1.0

        # 3. Warning count (fewer is better)
        warning_factor = max(0.0, 1.0 - len(self._warnings) * 0.1)

        score = (peak_factor * 0.5 + savings_factor * 0.3 + warning_factor * 0.2)

        if score >= 0.8:
            status = "healthy"
        elif score >= 0.6:
            status = "warning"
        elif score >= 0.4:
            status = "degraded"
        else:
            status = "critical"

        return score, status

    def _generate_recommendations(self) -> list[str]:
        """Generate actionable recommendations based on metrics."""
        recommendations: list[str] = []

        if self._peak_usage > 0.9:
            recommendations.append(
                "Consider enabling aggressive compression earlier in the session"
            )

        if self._peak_usage > 0.7 and not self._phase_metrics.get(AgentPhase.ORIENTATION):
            recommendations.append(
                "Use orientation cache to reduce early context consumption"
            )

        if len(self._snapshots) > 20 and self._peak_usage > 0.6:
            recommendations.append(
                "Long session detected — consider session splitting or "
                "proactive compression at phase transitions"
            )

        last = self._snapshots[-1] if self._snapshots else None
        if last and last.savings_ratio < 0.2 and last.usage_fraction > 0.5:
            recommendations.append(
                "Low compression savings with high usage — "
                "enable more aggressive transform pipelines"
            )

        return recommendations
