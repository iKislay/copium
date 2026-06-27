"""Token budget dashboard for compression observability.

Provides real-time visualization of token usage, compression breakdowns,
and semantic preservation scoring. This is a key differentiator vs
ContextCrumb which only offers basic inspection tools.

Features:
- Per-section compression ratio breakdown
- Semantic preservation score
- Cost/latency impact tracking
- Compression diff visualization
- Session-level token budget tracking
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SectionMetrics:
    """Metrics for a single content section."""

    name: str
    content_type: str
    original_tokens: int
    compressed_tokens: int
    compression_mode: str = ""
    preservation_score: float = 1.0  # 1.0 = perfect preservation
    duration_ms: float = 0.0

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens == 0:
            return 1.0
        return self.compressed_tokens / self.original_tokens

    @property
    def tokens_saved(self) -> int:
        return max(0, self.original_tokens - self.compressed_tokens)

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (self.tokens_saved / self.original_tokens) * 100


@dataclass
class SessionBudget:
    """Token budget tracking for a session."""

    max_tokens: int = 128000  # Default context window
    used_tokens: int = 0
    compressed_tokens: int = 0
    system_prompt_tokens: int = 0
    history_tokens: int = 0
    tool_tokens: int = 0
    current_turn_tokens: int = 0

    @property
    def available_tokens(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def usage_pct(self) -> float:
        if self.max_tokens == 0:
            return 0.0
        return (self.used_tokens / self.max_tokens) * 100

    @property
    def total_saved(self) -> int:
        return max(0, self.compressed_tokens)

    def is_near_limit(self, threshold: float = 0.9) -> bool:
        """Check if near context window limit."""
        return self.usage_pct >= threshold * 100


@dataclass
class CostEstimate:
    """Cost estimate for token usage."""

    input_tokens: int = 0
    output_tokens: int = 0
    input_cost_per_mtok: float = 3.0  # $/M tokens (default: Claude Sonnet)
    output_cost_per_mtok: float = 15.0

    @property
    def input_cost(self) -> float:
        return (self.input_tokens / 1_000_000) * self.input_cost_per_mtok

    @property
    def output_cost(self) -> float:
        return (self.output_tokens / 1_000_000) * self.output_cost_per_mtok

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost


@dataclass
class DiffSegment:
    """A segment in a compression diff."""

    text: str
    status: str  # "kept", "compressed", "removed"
    original_tokens: int = 0
    compressed_tokens: int = 0


@dataclass
class CompressionDiff:
    """Diff showing what was compressed/removed/kept."""

    segments: list[DiffSegment] = field(default_factory=list)

    @property
    def kept_tokens(self) -> int:
        return sum(s.original_tokens for s in self.segments if s.status == "kept")

    @property
    def compressed_tokens(self) -> int:
        return sum(s.compressed_tokens for s in self.segments if s.status == "compressed")

    @property
    def removed_tokens(self) -> int:
        return sum(s.original_tokens for s in self.segments if s.status == "removed")

    @property
    def total_original(self) -> int:
        return sum(s.original_tokens for s in self.segments)

    def summary(self) -> str:
        """Human-readable diff summary."""
        return (
            f"Kept: {self.kept_tokens} tokens, "
            f"Compressed: {self.compressed_tokens} tokens, "
            f"Removed: {self.removed_tokens} tokens"
        )


class CompressionDashboard:
    """Token budget and compression dashboard.

    Provides observability into compression effectiveness that
    ContextCrumb completely lacks. Shows:
    - Real-time token budget usage
    - Per-section compression breakdown
    - Cost savings estimates
    - Semantic preservation scores
    """

    def __init__(self, max_tokens: int = 128000):
        self._budget = SessionBudget(max_tokens=max_tokens)
        self._sections: list[SectionMetrics] = []
        self._history: list[dict[str, Any]] = []
        self._start_time = time.time()

    def record_compression(
        self,
        *,
        name: str,
        content_type: str,
        original_tokens: int,
        compressed_tokens: int,
        mode: str = "",
        preservation_score: float = 1.0,
        duration_ms: float = 0.0,
    ) -> SectionMetrics:
        """Record a compression event.

        Args:
            name: Section name/identifier.
            content_type: Type of content compressed.
            original_tokens: Tokens before compression.
            compressed_tokens: Tokens after compression.
            mode: Compression mode used.
            preservation_score: Semantic preservation (0-1).
            duration_ms: Time taken.

        Returns:
            SectionMetrics for the recorded event.
        """
        metrics = SectionMetrics(
            name=name,
            content_type=content_type,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_mode=mode,
            preservation_score=preservation_score,
            duration_ms=duration_ms,
        )
        self._sections.append(metrics)
        self._budget.compressed_tokens += metrics.tokens_saved
        self._budget.used_tokens += compressed_tokens

        self._history.append({
            "timestamp": time.time(),
            "section": name,
            "saved": metrics.tokens_saved,
            "mode": mode,
        })

        return metrics

    def update_budget(
        self,
        *,
        system_prompt_tokens: int | None = None,
        history_tokens: int | None = None,
        tool_tokens: int | None = None,
        current_turn_tokens: int | None = None,
    ) -> None:
        """Update token budget components."""
        if system_prompt_tokens is not None:
            self._budget.system_prompt_tokens = system_prompt_tokens
        if history_tokens is not None:
            self._budget.history_tokens = history_tokens
        if tool_tokens is not None:
            self._budget.tool_tokens = tool_tokens
        if current_turn_tokens is not None:
            self._budget.current_turn_tokens = current_turn_tokens

        self._budget.used_tokens = (
            self._budget.system_prompt_tokens
            + self._budget.history_tokens
            + self._budget.tool_tokens
            + self._budget.current_turn_tokens
        )

    @property
    def budget(self) -> SessionBudget:
        """Get current session budget."""
        return self._budget

    @property
    def sections(self) -> list[SectionMetrics]:
        """Get all recorded sections."""
        return self._sections

    @property
    def total_tokens_saved(self) -> int:
        """Total tokens saved across all sections."""
        return sum(s.tokens_saved for s in self._sections)

    @property
    def average_compression_ratio(self) -> float:
        """Average compression ratio across all sections."""
        if not self._sections:
            return 1.0
        total_orig = sum(s.original_tokens for s in self._sections)
        total_comp = sum(s.compressed_tokens for s in self._sections)
        if total_orig == 0:
            return 1.0
        return total_comp / total_orig

    @property
    def average_preservation_score(self) -> float:
        """Average semantic preservation score."""
        if not self._sections:
            return 1.0
        return sum(s.preservation_score for s in self._sections) / len(self._sections)

    def estimate_cost_savings(
        self,
        input_cost_per_mtok: float = 3.0,
        output_cost_per_mtok: float = 15.0,
    ) -> CostEstimate:
        """Estimate cost savings from compression.

        Args:
            input_cost_per_mtok: Cost per million input tokens.
            output_cost_per_mtok: Cost per million output tokens.

        Returns:
            CostEstimate with savings breakdown.
        """
        return CostEstimate(
            input_tokens=self.total_tokens_saved,
            output_tokens=0,  # Compression only affects input
            input_cost_per_mtok=input_cost_per_mtok,
            output_cost_per_mtok=output_cost_per_mtok,
        )

    def generate_diff(self, original: str, compressed: str) -> CompressionDiff:
        """Generate a compression diff showing what changed.

        Args:
            original: Original text.
            compressed: Compressed text.

        Returns:
            CompressionDiff with segment breakdown.
        """
        orig_lines = original.split("\n")
        comp_lines = compressed.split("\n")
        segments: list[DiffSegment] = []

        comp_set = set(comp_lines)

        for line in orig_lines:
            tokens = len(line) // 4 + 1
            if line in comp_set:
                segments.append(DiffSegment(
                    text=line, status="kept", original_tokens=tokens
                ))
            else:
                # Check if it was compressed (similar line exists)
                similar = self._find_similar(line, comp_lines)
                if similar:
                    segments.append(DiffSegment(
                        text=line,
                        status="compressed",
                        original_tokens=tokens,
                        compressed_tokens=len(similar) // 4 + 1,
                    ))
                else:
                    segments.append(DiffSegment(
                        text=line, status="removed", original_tokens=tokens
                    ))

        return CompressionDiff(segments=segments)

    def render_summary(self) -> str:
        """Render a human-readable dashboard summary."""
        elapsed = time.time() - self._start_time
        lines = [
            "╔══════════════════════════════════════════╗",
            "║       Copium Compression Dashboard       ║",
            "╠══════════════════════════════════════════╣",
            f"║ Budget: {self._budget.used_tokens:,}/{self._budget.max_tokens:,} tokens ({self._budget.usage_pct:.1f}%)",
            f"║ Saved: {self.total_tokens_saved:,} tokens total",
            f"║ Avg ratio: {self.average_compression_ratio:.2f}",
            f"║ Preservation: {self.average_preservation_score:.2f}",
            f"║ Sections: {len(self._sections)}",
            f"║ Session: {elapsed:.1f}s",
            "╚══════════════════════════════════════════╝",
        ]
        return "\n".join(lines)

    @staticmethod
    def _find_similar(line: str, candidates: list[str]) -> str | None:
        """Find a similar line in candidates (simple substring match)."""
        if not line.strip():
            return None
        # Check if any candidate contains the key parts
        words = line.split()
        if len(words) < 2:
            return None
        key_word = words[0]
        for candidate in candidates:
            if key_word in candidate and candidate != line:
                return candidate
        return None
