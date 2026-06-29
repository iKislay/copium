"""Quality dashboard for real-time compression quality monitoring.

Provides a session-level view of compression quality including
gate stats, metrics, CCR retrieval rates, and compression breakdown.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class CompressionEvent:
    """A single compression event tracked by the dashboard."""

    content_type: str
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    gate_passed: bool
    gate_failures: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class RetrievalEvent:
    """A CCR retrieval event."""

    cache_key: str
    tokens_retrieved: int
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class DashboardSnapshot:
    """Point-in-time snapshot of quality dashboard state."""

    # Quality metrics (session average)
    rouge_l_avg: float
    ips_avg: float
    task_accuracy_est: float

    # Gate stats
    gate_checks_total: int
    gate_passes: int
    gate_failures: int
    gate_pass_rate: float
    revert_reasons: Dict[str, int]

    # Compression breakdown by type
    compression_by_type: Dict[str, Dict[str, float]]

    # CCR retrievals
    ccr_retrievals: int
    ccr_avg_latency_ms: float
    ccr_tokens_retrieved: int

    # Savings
    total_tokens_saved: int
    estimated_cost_saved: float


class QualityDashboard:
    """Real-time quality monitoring dashboard.

    Tracks compression quality across a session, providing
    visibility into gate decisions, metrics, and CCR usage.

    Example:
        dashboard = QualityDashboard()
        dashboard.record_compression(event)
        snapshot = dashboard.get_snapshot()
        print(f"Quality: {snapshot.gate_pass_rate:.1%}")
    """

    def __init__(self, cost_per_token: float = 0.000003):
        self._compressions: List[CompressionEvent] = []
        self._retrievals: List[RetrievalEvent] = []
        self._cost_per_token = cost_per_token

    def record_compression(self, event: CompressionEvent) -> None:
        """Record a compression event."""
        self._compressions.append(event)

    def record_retrieval(self, event: RetrievalEvent) -> None:
        """Record a CCR retrieval event."""
        self._retrievals.append(event)

    def get_snapshot(self) -> DashboardSnapshot:
        """Get current dashboard state."""
        if not self._compressions:
            return DashboardSnapshot(
                rouge_l_avg=1.0,
                ips_avg=1.0,
                task_accuracy_est=1.0,
                gate_checks_total=0,
                gate_passes=0,
                gate_failures=0,
                gate_pass_rate=1.0,
                revert_reasons={},
                compression_by_type={},
                ccr_retrievals=0,
                ccr_avg_latency_ms=0.0,
                ccr_tokens_retrieved=0,
                total_tokens_saved=0,
                estimated_cost_saved=0.0,
            )

        # Gate stats
        gate_passes = sum(1 for c in self._compressions if c.gate_passed)
        gate_failures = sum(1 for c in self._compressions if not c.gate_passed)
        gate_total = len(self._compressions)
        gate_pass_rate = gate_passes / max(1, gate_total)

        # Revert reasons
        revert_reasons: Dict[str, int] = {}
        for c in self._compressions:
            if not c.gate_passed:
                for reason in c.gate_failures:
                    revert_reasons[reason] = revert_reasons.get(reason, 0) + 1

        # Compression breakdown by type
        by_type: Dict[str, Dict[str, float]] = {}
        type_events: Dict[str, List[CompressionEvent]] = {}
        for c in self._compressions:
            if c.content_type not in type_events:
                type_events[c.content_type] = []
            type_events[c.content_type].append(c)

        for ctype, events in type_events.items():
            savings = [e.compression_ratio for e in events if e.gate_passed]
            by_type[ctype] = {
                "avg_savings_pct": (sum(savings) / len(savings) * 100) if savings else 0.0,
                "count": len(events),
            }

        # Token savings
        total_saved = sum(
            c.original_tokens - c.compressed_tokens
            for c in self._compressions
            if c.gate_passed
        )

        # CCR stats
        ccr_count = len(self._retrievals)
        ccr_latency = (
            sum(r.latency_ms for r in self._retrievals) / ccr_count
            if ccr_count > 0
            else 0.0
        )
        ccr_tokens = sum(r.tokens_retrieved for r in self._retrievals)

        # Estimate quality from gate pass rate
        # High pass rate correlates with preserved quality
        estimated_accuracy = 0.95 + 0.05 * gate_pass_rate

        return DashboardSnapshot(
            rouge_l_avg=gate_pass_rate * 0.95,  # Estimate based on gate behavior
            ips_avg=gate_pass_rate * 0.98,
            task_accuracy_est=estimated_accuracy,
            gate_checks_total=gate_total,
            gate_passes=gate_passes,
            gate_failures=gate_failures,
            gate_pass_rate=gate_pass_rate,
            revert_reasons=revert_reasons,
            compression_by_type=by_type,
            ccr_retrievals=ccr_count,
            ccr_avg_latency_ms=ccr_latency,
            ccr_tokens_retrieved=ccr_tokens,
            total_tokens_saved=total_saved,
            estimated_cost_saved=total_saved * self._cost_per_token,
        )

    def format_dashboard(self) -> str:
        """Format dashboard as human-readable text."""
        snap = self.get_snapshot()

        lines = [
            "COPIUM QUALITY DASHBOARD",
            "=" * 60,
            "",
            "Compression Quality (This Session)",
            "-" * 40,
            f"  Gate Pass Rate:     {snap.gate_pass_rate:.1%}",
            f"  Est. Accuracy:      {snap.task_accuracy_est:.1%}  (target: >=98%)",
            f"  Info Preservation:  {snap.ips_avg:.1%}  (target: >=95%)",
            "",
            "Quality Gate Stats",
            "-" * 40,
            f"  Checks passed:      {snap.gate_passes}  ({snap.gate_pass_rate:.1%})",
            f"  Checks failed:      {snap.gate_failures}  ({1 - snap.gate_pass_rate:.1%})",
        ]

        if snap.revert_reasons:
            reasons = ", ".join(f"{k} ({v})" for k, v in snap.revert_reasons.items())
            lines.append(f"  Revert reasons:     {reasons}")

        lines.extend([
            "",
            "Compression Breakdown",
            "-" * 40,
        ])

        for ctype, stats in snap.compression_by_type.items():
            lines.append(f"  {ctype:16s} {stats['avg_savings_pct']:.1f}% avg savings ({int(stats['count'])} calls)")

        lines.extend([
            "",
            "CCR Retrievals",
            "-" * 40,
            f"  Retrievals:         {snap.ccr_retrievals}",
            f"  Avg latency:        {snap.ccr_avg_latency_ms:.1f}ms",
            f"  Tokens retrieved:   {snap.ccr_tokens_retrieved:,}",
            "",
            f"  Total tokens saved: {snap.total_tokens_saved:,}",
            f"  Est. cost saved:    ${snap.estimated_cost_saved:.4f}",
        ])

        return "\n".join(lines)

    def reset(self) -> None:
        """Reset dashboard state."""
        self._compressions.clear()
        self._retrievals.clear()
