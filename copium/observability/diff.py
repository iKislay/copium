"""Compression diff visualization tools.

Provides detailed diff views showing exactly what was compressed, kept,
or removed during the compression process. This is a key differentiator
vs ContextCrumb which only offers basic inspection tools.

Features:
- Line-level diff with semantic awareness
- Token-level compression breakdown
- Restoration map for reversible operations
- Visual rendering for terminal and JSON output
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class DiffStatus(Enum):
    """Status of a diff segment."""

    KEPT = "kept"
    COMPRESSED = "compressed"
    REMOVED = "removed"
    ADDED = "added"  # New content from compression (e.g., summaries)


@dataclass
class DiffSegment:
    """A segment in the compression diff."""

    text: str
    status: DiffStatus
    original_text: str = ""
    line_number: int = 0
    original_tokens: int = 0
    compressed_tokens: int = 0
    compression_mode: str = ""
    restorable: bool = False
    restoration_key: str = ""

    @property
    def tokens_saved(self) -> int:
        if self.status == DiffStatus.REMOVED:
            return self.original_tokens
        if self.status == DiffStatus.COMPRESSED:
            return max(0, self.original_tokens - self.compressed_tokens)
        return 0

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (self.tokens_saved / self.original_tokens) * 100


@dataclass
class DiffSummary:
    """Summary statistics for a compression diff."""

    total_lines: int = 0
    kept_lines: int = 0
    compressed_lines: int = 0
    removed_lines: int = 0
    added_lines: int = 0
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0
    restorable_segments: int = 0

    @property
    def total_tokens_saved(self) -> int:
        return max(0, self.total_original_tokens - self.total_compressed_tokens)

    @property
    def compression_ratio(self) -> float:
        if self.total_original_tokens == 0:
            return 1.0
        return self.total_compressed_tokens / self.total_original_tokens

    @property
    def savings_pct(self) -> float:
        if self.total_original_tokens == 0:
            return 0.0
        return (self.total_tokens_saved / self.total_original_tokens) * 100


@dataclass
class RestorationMap:
    """Map of compressed segments to their original content.

    Used for CCR-based restoration of compressed content.
    """

    entries: dict[str, str] = field(default_factory=dict)

    def add(self, key: str, original: str) -> None:
        """Add a restoration entry."""
        self.entries[key] = original

    def restore(self, key: str) -> str | None:
        """Restore original content by key."""
        return self.entries.get(key)

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def total_stored_tokens(self) -> int:
        return sum(len(v) // 4 for v in self.entries.values())


class CompressionDiffEngine:
    """Engine for generating detailed compression diffs.

    Produces line-by-line diffs showing exactly what compression did,
    with support for restoration maps and visual rendering.

    Example:
        >>> engine = CompressionDiffEngine()
        >>> diff = engine.generate_diff(original, compressed)
        >>> print(engine.render_terminal(diff))
        >>> print(f"Saved {diff.summary.savings_pct:.1f}%")
    """

    def __init__(
        self,
        *,
        context_lines: int = 3,
        token_estimator: str = "char4",
    ):
        """Initialize diff engine.

        Args:
            context_lines: Number of context lines around changes.
            token_estimator: Method for token estimation ("char4" or "word").
        """
        self._context_lines = context_lines
        self._token_estimator = token_estimator

    def generate_diff(
        self,
        original: str,
        compressed: str,
        *,
        restoration_keys: dict[int, str] | None = None,
    ) -> list[DiffSegment]:
        """Generate a detailed compression diff.

        Args:
            original: Original text before compression.
            compressed: Text after compression.
            restoration_keys: Optional mapping of line numbers to CCR keys.

        Returns:
            List of DiffSegments describing the transformation.
        """
        orig_lines = original.split("\n")
        comp_lines = compressed.split("\n")

        matcher = difflib.SequenceMatcher(None, orig_lines, comp_lines)
        segments: list[DiffSegment] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for idx in range(i1, i2):
                    tokens = self._estimate_tokens(orig_lines[idx])
                    segments.append(DiffSegment(
                        text=orig_lines[idx],
                        status=DiffStatus.KEPT,
                        line_number=idx + 1,
                        original_tokens=tokens,
                        compressed_tokens=tokens,
                    ))
            elif tag == "delete":
                for idx in range(i1, i2):
                    tokens = self._estimate_tokens(orig_lines[idx])
                    key = (restoration_keys or {}).get(idx, "")
                    segments.append(DiffSegment(
                        text=orig_lines[idx],
                        status=DiffStatus.REMOVED,
                        line_number=idx + 1,
                        original_tokens=tokens,
                        compressed_tokens=0,
                        restorable=bool(key),
                        restoration_key=key,
                    ))
            elif tag == "insert":
                for idx in range(j1, j2):
                    tokens = self._estimate_tokens(comp_lines[idx])
                    segments.append(DiffSegment(
                        text=comp_lines[idx],
                        status=DiffStatus.ADDED,
                        line_number=idx + 1,
                        original_tokens=0,
                        compressed_tokens=tokens,
                    ))
            elif tag == "replace":
                # Lines were compressed (replaced with shorter versions)
                for idx in range(i1, i2):
                    orig_tokens = self._estimate_tokens(orig_lines[idx])
                    # Find corresponding compressed line if available
                    comp_idx = j1 + (idx - i1)
                    if comp_idx < j2:
                        comp_tokens = self._estimate_tokens(comp_lines[comp_idx])
                        key = (restoration_keys or {}).get(idx, "")
                        segments.append(DiffSegment(
                            text=comp_lines[comp_idx],
                            original_text=orig_lines[idx],
                            status=DiffStatus.COMPRESSED,
                            line_number=idx + 1,
                            original_tokens=orig_tokens,
                            compressed_tokens=comp_tokens,
                            restorable=bool(key),
                            restoration_key=key,
                        ))
                    else:
                        segments.append(DiffSegment(
                            text=orig_lines[idx],
                            status=DiffStatus.REMOVED,
                            line_number=idx + 1,
                            original_tokens=orig_tokens,
                            compressed_tokens=0,
                        ))
                # Any extra compressed lines that don't map to originals
                for idx in range(i2 - i1 + j1, j2):
                    if idx < len(comp_lines):
                        tokens = self._estimate_tokens(comp_lines[idx])
                        segments.append(DiffSegment(
                            text=comp_lines[idx],
                            status=DiffStatus.ADDED,
                            line_number=idx + 1,
                            original_tokens=0,
                            compressed_tokens=tokens,
                        ))

        return segments

    def build_restoration_map(
        self,
        segments: list[DiffSegment],
        original: str,
    ) -> RestorationMap:
        """Build a restoration map from diff segments.

        Creates a mapping that allows compressed content to be restored
        to its original form (CCR integration).

        Args:
            segments: Diff segments from generate_diff.
            original: Original text for restoration entries.

        Returns:
            RestorationMap with restoration entries.
        """
        rmap = RestorationMap()
        for segment in segments:
            if segment.restorable and segment.restoration_key:
                original_text = segment.original_text or segment.text
                rmap.add(segment.restoration_key, original_text)
        return rmap

    def summarize(self, segments: list[DiffSegment]) -> DiffSummary:
        """Generate summary statistics from diff segments.

        Args:
            segments: Diff segments to summarize.

        Returns:
            DiffSummary with aggregate statistics.
        """
        summary = DiffSummary()
        summary.total_lines = len(segments)

        for seg in segments:
            if seg.status == DiffStatus.KEPT:
                summary.kept_lines += 1
                summary.total_original_tokens += seg.original_tokens
                summary.total_compressed_tokens += seg.compressed_tokens
            elif seg.status == DiffStatus.COMPRESSED:
                summary.compressed_lines += 1
                summary.total_original_tokens += seg.original_tokens
                summary.total_compressed_tokens += seg.compressed_tokens
                if seg.restorable:
                    summary.restorable_segments += 1
            elif seg.status == DiffStatus.REMOVED:
                summary.removed_lines += 1
                summary.total_original_tokens += seg.original_tokens
                if seg.restorable:
                    summary.restorable_segments += 1
            elif seg.status == DiffStatus.ADDED:
                summary.added_lines += 1
                summary.total_compressed_tokens += seg.compressed_tokens

        return summary

    def render_terminal(self, segments: list[DiffSegment]) -> str:
        """Render diff for terminal output with ANSI colors.

        Args:
            segments: Diff segments to render.

        Returns:
            Formatted string with ANSI color codes.
        """
        lines: list[str] = []
        summary = self.summarize(segments)

        lines.append("\033[1m--- Compression Diff ---\033[0m")
        lines.append(f"Saved: {summary.total_tokens_saved} tokens ({summary.savings_pct:.1f}%)")
        lines.append("")

        for seg in segments:
            if seg.status == DiffStatus.KEPT:
                lines.append(f"  {seg.text}")
            elif seg.status == DiffStatus.COMPRESSED:
                lines.append(f"\033[33m~ {seg.text}\033[0m")
                lines.append(f"\033[90m  (was: {seg.original_text[:80]}...)\033[0m")
            elif seg.status == DiffStatus.REMOVED:
                lines.append(f"\033[31m- {seg.text}\033[0m")
            elif seg.status == DiffStatus.ADDED:
                lines.append(f"\033[32m+ {seg.text}\033[0m")

        lines.append("")
        lines.append(
            f"Summary: {summary.kept_lines} kept, "
            f"{summary.compressed_lines} compressed, "
            f"{summary.removed_lines} removed"
        )
        if summary.restorable_segments > 0:
            lines.append(
                f"Restorable: {summary.restorable_segments} segments (CCR)"
            )

        return "\n".join(lines)

    def render_json(self, segments: list[DiffSegment]) -> dict[str, Any]:
        """Render diff as JSON-serializable dictionary.

        Args:
            segments: Diff segments to render.

        Returns:
            Dictionary with diff data.
        """
        summary = self.summarize(segments)
        return {
            "summary": {
                "total_lines": summary.total_lines,
                "kept_lines": summary.kept_lines,
                "compressed_lines": summary.compressed_lines,
                "removed_lines": summary.removed_lines,
                "added_lines": summary.added_lines,
                "tokens_saved": summary.total_tokens_saved,
                "savings_pct": round(summary.savings_pct, 2),
                "compression_ratio": round(summary.compression_ratio, 3),
                "restorable_segments": summary.restorable_segments,
            },
            "segments": [
                {
                    "text": seg.text,
                    "status": seg.status.value,
                    "line_number": seg.line_number,
                    "original_tokens": seg.original_tokens,
                    "compressed_tokens": seg.compressed_tokens,
                    "tokens_saved": seg.tokens_saved,
                    "restorable": seg.restorable,
                }
                for seg in segments
            ],
        }

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        if not text:
            return 0
        if self._token_estimator == "word":
            return len(text.split())
        # Default: char4 (4 chars per token approximation)
        return max(1, len(text) // 4)
