"""Tool output bloat compression report.

Exports per-session compression stats focused specifically on tool output
bloat — the #1 community pain point. Formats output for terminal display,
structured JSON, and community sharing.

Usage:
    >>> from copium.observability.compression_report import CompressionReport
    >>> report = CompressionReport()
    >>> report.record_tool_compression("grep", 500, 25, 12500, 625)
    >>> print(report.render_terminal())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCompressionEntry:
    """A single tool output compression event."""

    tool_name: str
    original_items: int  # e.g., number of grep matches
    compressed_items: int
    original_chars: int
    compressed_chars: int
    transform_used: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def items_reduction_pct(self) -> float:
        if self.original_items == 0:
            return 0.0
        return ((self.original_items - self.compressed_items) / self.original_items) * 100

    @property
    def chars_reduction_pct(self) -> float:
        if self.original_chars == 0:
            return 0.0
        return ((self.original_chars - self.compressed_chars) / self.original_chars) * 100


@dataclass
class SessionCompressionStats:
    """Aggregate statistics for a session."""

    total_tool_calls: int = 0
    total_original_chars: int = 0
    total_compressed_chars: int = 0
    total_dedup_hits: int = 0
    total_ccr_retrievals: int = 0
    total_prefilter_saves: int = 0
    turn_count: int = 0
    session_start: float = field(default_factory=time.time)

    @property
    def total_chars_saved(self) -> int:
        return max(0, self.total_original_chars - self.total_compressed_chars)

    @property
    def overall_reduction_pct(self) -> float:
        if self.total_original_chars == 0:
            return 0.0
        return (self.total_chars_saved / self.total_original_chars) * 100

    @property
    def estimated_tokens_saved(self) -> int:
        """Estimate tokens saved (approx 4 chars per token)."""
        return self.total_chars_saved // 4

    @property
    def estimated_cost_saved(self) -> float:
        """Estimate cost saved at Claude Sonnet pricing ($3/MTok input)."""
        return (self.estimated_tokens_saved / 1_000_000) * 3.0

    @property
    def session_duration_s(self) -> float:
        return time.time() - self.session_start


class CompressionReport:
    """Tool output bloat compression report.

    Tracks and reports on tool output compression for a session,
    focused on the community's #1 pain point: tool output bloat.
    """

    def __init__(self) -> None:
        self._entries: list[ToolCompressionEntry] = []
        self._stats = SessionCompressionStats()
        self._per_tool: dict[str, list[ToolCompressionEntry]] = {}

    def record_tool_compression(
        self,
        tool_name: str,
        original_items: int,
        compressed_items: int,
        original_chars: int,
        compressed_chars: int,
        transform_used: str = "",
    ) -> None:
        """Record a tool output compression event."""
        entry = ToolCompressionEntry(
            tool_name=tool_name,
            original_items=original_items,
            compressed_items=compressed_items,
            original_chars=original_chars,
            compressed_chars=compressed_chars,
            transform_used=transform_used,
        )
        self._entries.append(entry)
        self._per_tool.setdefault(tool_name, []).append(entry)

        # Update aggregate stats
        self._stats.total_tool_calls += 1
        self._stats.total_original_chars += original_chars
        self._stats.total_compressed_chars += compressed_chars

    def record_dedup_hit(self) -> None:
        """Record a session dedup hit."""
        self._stats.total_dedup_hits += 1

    def record_ccr_retrieval(self) -> None:
        """Record a CCR retrieval event."""
        self._stats.total_ccr_retrievals += 1

    def record_prefilter_save(self) -> None:
        """Record a pre-filter save event."""
        self._stats.total_prefilter_saves += 1

    def record_turn(self) -> None:
        """Increment turn count."""
        self._stats.turn_count += 1

    @property
    def stats(self) -> SessionCompressionStats:
        """Get aggregate session stats."""
        return self._stats

    def render_terminal(self) -> str:
        """Render a terminal-friendly compression report.

        Output format matches the community plan:
        === Copium Compression Report ===
        Session: 47 turns | 284K tokens → 89K tokens (69% saved)
        ├── SearchCompressor: 500 → 30 matches (94% saved)
        ...
        """
        s = self._stats
        tokens_before = s.total_original_chars // 4
        tokens_after = s.total_compressed_chars // 4

        lines = [
            "",
            "=== Copium Compression Report ===",
            f"Session: {s.turn_count} turns | {self._format_tokens(tokens_before)} → "
            f"{self._format_tokens(tokens_after)} ({s.overall_reduction_pct:.0f}% saved)",
        ]

        # Per-tool breakdown
        for tool_name, entries in sorted(self._per_tool.items()):
            total_orig = sum(e.original_chars for e in entries)
            total_comp = sum(e.compressed_chars for e in entries)
            pct = ((total_orig - total_comp) / total_orig * 100) if total_orig > 0 else 0
            calls = len(entries)
            lines.append(
                f"├── {tool_name}: {calls} calls, "
                f"{self._format_chars(total_orig)} → {self._format_chars(total_comp)} "
                f"({pct:.0f}% saved)"
            )

        # Dedup and CCR stats
        if s.total_dedup_hits > 0:
            lines.append(f"├── SessionDedup: {s.total_dedup_hits} duplicate outputs removed")
        if s.total_ccr_retrievals > 0:
            lines.append(f"├── CCR retrievals: {s.total_ccr_retrievals} originals retrieved on demand")
        if s.total_prefilter_saves > 0:
            lines.append(f"├── ToolPrefilter: {s.total_prefilter_saves} outputs pre-filtered")

        # Cost estimate
        lines.append(f"└── Cost savings: ~${s.estimated_cost_saved:.2f}/session (at Claude Sonnet pricing)")
        lines.append("")

        return "\n".join(lines)

    def render_json(self) -> dict[str, Any]:
        """Render report as structured JSON for programmatic consumption."""
        s = self._stats
        per_tool_summary = {}
        for tool_name, entries in self._per_tool.items():
            total_orig = sum(e.original_chars for e in entries)
            total_comp = sum(e.compressed_chars for e in entries)
            per_tool_summary[tool_name] = {
                "calls": len(entries),
                "original_chars": total_orig,
                "compressed_chars": total_comp,
                "chars_saved": total_orig - total_comp,
                "reduction_pct": ((total_orig - total_comp) / total_orig * 100) if total_orig > 0 else 0,
            }

        return {
            "session": {
                "turn_count": s.turn_count,
                "duration_s": round(s.session_duration_s, 1),
                "total_tool_calls": s.total_tool_calls,
            },
            "compression": {
                "original_chars": s.total_original_chars,
                "compressed_chars": s.total_compressed_chars,
                "chars_saved": s.total_chars_saved,
                "reduction_pct": round(s.overall_reduction_pct, 1),
                "estimated_tokens_saved": s.estimated_tokens_saved,
                "estimated_cost_saved_usd": round(s.estimated_cost_saved, 4),
            },
            "per_tool": per_tool_summary,
            "features": {
                "dedup_hits": s.total_dedup_hits,
                "ccr_retrievals": s.total_ccr_retrievals,
                "prefilter_saves": s.total_prefilter_saves,
            },
        }

    @staticmethod
    def _format_tokens(tokens: int) -> str:
        """Format token count as human-readable."""
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M"
        if tokens >= 1_000:
            return f"{tokens / 1_000:.0f}K"
        return str(tokens)

    @staticmethod
    def _format_chars(chars: int) -> str:
        """Format char count as human-readable."""
        if chars >= 1_000_000:
            return f"{chars / 1_000_000:.1f}M chars"
        if chars >= 1_000:
            return f"{chars / 1_000:.0f}K chars"
        return f"{chars} chars"
