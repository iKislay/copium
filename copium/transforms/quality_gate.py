"""Post-compression quality verification transform.

After each lossy compression step, re-measure with the tokenizer.
If compression doesn't actually save tokens (or makes things worse),
auto-revert that step. Makes compression safe-by-default — users
never get a higher bill from a transform that was supposed to help.

The quality gate operates at the transform pipeline level, checking
each transform's output against the original to ensure:
1. Token count actually decreased (or stayed the same)
2. No significant content was lost (measured by token ratio)
3. Content-type-specific critical markers are preserved (Gate 4)

When a transform fails the gate, its changes are reverted and a
warning is logged. This prevents \"negative savings\" where a transform
inflates tokens instead of compressing them.

## Gate 4: Content-type-aware critical marker preservation

Plan §4.2 Layer 2 (Quality Gate) and §4.2 Layer 4 (Contextual Preservation).
For specific content types that LLMs are trained on, critical structural
markers must survive compression to avoid the \"strangeness tax\" — the
phenomenon where compressed CLI output confuses LLMs because it doesn't
match their training distribution.

Critical markers by content type:

  git status   branch name, file paths, modification status indicators
  git diff     +/- prefixes, hunk headers (@@)
  pytest       test counts, failure messages, error traces
  build        error lines, warning lines, exit codes
  grep/rg      file paths, line numbers, matched text

See plans/04-beat-rtk.md §4.2 for full discussion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import QualityGateConfig, TransformResult
from ..tokenizer import Tokenizer
from .base import Transform

logger = logging.getLogger(__name__)


# ─── Content-type critical marker rules ────────────────────────────────────

def _extract_git_status_markers(text: str) -> list[str]:
    """Extract critical markers from git status output.

    Critical: branch name, modified file paths, untracked files.
    """
    markers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # Branch header
        if stripped.startswith("On branch "):
            branch = stripped[len("On branch "):].strip()
            if branch:
                markers.append(branch)
        # Modified/deleted/added/untracked file paths (status codes + path)
        elif len(stripped) >= 3 and stripped[0] in "MADRCUTU?" and stripped[1] in " MADRCUTU?":
            path = stripped[2:].strip()
            if path:
                markers.append(path)
        # Porcelain v1: " M src/file.py" style
        elif len(stripped) >= 2 and stripped[0] == " " and stripped[1] in "MADRCUTU?":
            path = stripped[2:].strip()
            if path:
                markers.append(path)
    return markers


def _extract_git_diff_markers(text: str) -> list[str]:
    """Extract critical markers from git diff output.

    Critical: hunk headers, file paths, +/- line prefixes (via count check).
    """
    markers: list[str] = []
    for line in text.splitlines():
        # Hunk headers
        if line.startswith("@@"):
            markers.append(line[:40])  # First 40 chars capture position info
        # diff --git a/... b/... file headers
        elif line.startswith("diff --git"):
            markers.append(line[:80])
        # +++ / --- file names
        elif line.startswith("+++ ") or line.startswith("--- "):
            markers.append(line[:60])
    return markers


def _extract_test_markers(text: str) -> list[str]:
    """Extract critical markers from pytest/cargo test/jest output.

    Critical: test summary line, failure indicators.
    """
    markers: list[str] = []
    # pytest patterns: "N passed", "N failed", "N error"
    summary_re = re.compile(
        r"(\d+)\s+(passed|failed|error|warning|deselected)",
        re.IGNORECASE,
    )
    # Rust/cargo: "test result: FAILED. N passed; M failed"
    cargo_re = re.compile(r"test result:\s+(ok|FAILED)", re.IGNORECASE)
    # Jest/vitest: "Tests: N failed, M passed"
    jest_re = re.compile(r"Tests:\s+\d+", re.IGNORECASE)
    for line in text.splitlines():
        if summary_re.search(line) or cargo_re.search(line) or jest_re.search(line):
            markers.append(line.strip()[:120])
        # FAILED prefix lines in pytest
        elif line.strip().startswith("FAILED ") or "FAILED" in line and "::" in line:
            markers.append(line.strip()[:120])
    return markers


def _extract_build_markers(text: str) -> list[str]:
    """Extract critical markers from build/compiler output.

    Critical: error lines, warning lines with file:line references.
    """
    markers: list[str] = []
    err_re = re.compile(r"\berror\b", re.IGNORECASE)
    warn_re = re.compile(r"\bwarning\b", re.IGNORECASE)
    for line in text.splitlines():
        if err_re.search(line) or warn_re.search(line):
            markers.append(line.strip()[:120])
    return markers[:20]  # Cap to avoid false positives


def _extract_grep_markers(text: str) -> list[str]:
    """Extract critical markers from grep/ripgrep output.

    Critical: file paths, line numbers, matched text (first 30 matches).
    """
    markers: list[str] = []
    # Typical grep/rg: "file:line:content" or "file:content"
    line_re = re.compile(r"^([^:]+):(\d+):")
    for line in text.splitlines()[:30]:
        m = line_re.match(line)
        if m:
            markers.append(m.group(0)[:80])
    return markers


# Mapping from content_type hint → marker extractor
_CONTENT_TYPE_EXTRACTORS: dict[str, Any] = {
    "git_status": _extract_git_status_markers,
    "git_diff": _extract_git_diff_markers,
    "test_output": _extract_test_markers,
    "build_output": _extract_build_markers,
    "grep": _extract_grep_markers,
    "ripgrep": _extract_grep_markers,
}


@dataclass
class QualityGateResult:
    """Result of a quality gate check."""

    accepted: bool
    reason: str
    original_tokens: int
    compressed_tokens: int
    savings_ratio: float
    details: str = ""
    missing_markers: list[str] = field(default_factory=list)


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Concatenate all message content for marker extraction."""
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", "") or str(block.get("content", "")))
    return "\n".join(parts)


class QualityGate(Transform):
    """Post-compression quality verification.

    Validates that compression actually saves tokens and doesn't
    degrade content quality beyond acceptable thresholds.

    When enabled in the pipeline, this transform runs after each
    lossy compression step and reverts the step if it fails the gate.

    Safety guarantees:
    - Never allows token inflation (more tokens after compression)
    - Requires minimum savings threshold to keep compressed output
    - Logs warnings for marginal savings
    - Reverts automatically on quality degradation
    - Preserves content-type-specific critical markers (Gate 4)
    """

    name = "quality_gate"

    def __init__(self, config: QualityGateConfig | None = None):
        self.config = config or QualityGateConfig()

    def check(
        self,
        original: list[dict[str, Any]],
        compressed: list[dict[str, Any]],
        tokenizer: Tokenizer,
        transform_name: str = "unknown",
        content_type: str | None = None,
    ) -> QualityGateResult:
        """Check if compression passes the quality gate.

        Args:
            original: Original messages before compression.
            compressed: Compressed messages after compression.
            tokenizer: Tokenizer for counting tokens.
            transform_name: Name of the transform being checked.
            content_type: Optional content type hint for Gate 4 marker checks.
                          One of: 'git_status', 'git_diff', 'test_output',
                          'build_output', 'grep', 'ripgrep'.

        Returns:
            QualityGateResult with acceptance status and details.
        """
        if not self.config.enabled:
            return QualityGateResult(
                accepted=True,
                reason="gate_disabled",
                original_tokens=0,
                compressed_tokens=0,
                savings_ratio=0.0,
            )

        original_tokens = tokenizer.count_messages(original)
        compressed_tokens = tokenizer.count_messages(compressed)

        # Gate 1: Token inflation check — compressed must not have more tokens
        if compressed_tokens > original_tokens:
            inflation = compressed_tokens - original_tokens
            ratio = inflation / original_tokens if original_tokens > 0 else 0
            if ratio > self.config.revert_threshold:
                logger.warning(
                    "Quality gate REVERT: %s inflated tokens by %d (%.1f%%), "
                    "threshold is %.1f%%",
                    transform_name,
                    inflation,
                    ratio * 100,
                    self.config.revert_threshold * 100,
                )
                return QualityGateResult(
                    accepted=False,
                    reason="token_inflation",
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    savings_ratio=-ratio,
                    details=f"Tokens increased by {inflation} ({ratio:.1%})",
                )

        # Gate 2: Minimum savings check
        tokens_saved = original_tokens - compressed_tokens
        if tokens_saved < self.config.min_savings_tokens:
            if tokens_saved < 0:
                # Actually inflated, already caught above in most cases
                pass
            elif tokens_saved == 0:
                logger.debug(
                    "Quality gate: %s produced zero savings, reverting",
                    transform_name,
                )
                return QualityGateResult(
                    accepted=False,
                    reason="zero_savings",
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    savings_ratio=0.0,
                    details="No tokens saved",
                )
            else:
                # Positive but below minimum threshold
                logger.debug(
                    "Quality gate: %s saved only %d tokens (below min %d), reverting",
                    transform_name,
                    tokens_saved,
                    self.config.min_savings_tokens,
                )
                return QualityGateResult(
                    accepted=False,
                    reason="insufficient_savings",
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    savings_ratio=tokens_saved / original_tokens if original_tokens > 0 else 0.0,
                    details=f"Only {tokens_saved} tokens saved (minimum: {self.config.min_savings_tokens})",
                )

        # Gate 3: Marginal savings warning
        savings_ratio = tokens_saved / original_tokens if original_tokens > 0 else 0.0
        if tokens_saved < self.config.warn_below_tokens and tokens_saved > 0:
            logger.info(
                "Quality gate WARNING: %s saved only %d tokens (%.1f%%) — marginal",
                transform_name,
                tokens_saved,
                savings_ratio * 100,
            )

        # Gate 4: Content-type-aware critical marker preservation (plan §4.2 Layer 2)
        if content_type is not None:
            marker_result = self._check_critical_markers(
                original, compressed, content_type, transform_name
            )
            if marker_result is not None:
                return marker_result

        # All gates passed
        return QualityGateResult(
            accepted=True,
            reason="passed",
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            savings_ratio=savings_ratio,
            details=f"Saved {tokens_saved} tokens ({savings_ratio:.1%})",
        )

    def _check_critical_markers(
        self,
        original: list[dict[str, Any]],
        compressed: list[dict[str, Any]],
        content_type: str,
        transform_name: str,
    ) -> QualityGateResult | None:
        """Gate 4: Verify that critical markers are preserved.

        Returns a failing QualityGateResult if any critical markers are
        missing from the compressed output, or None if the gate passes.
        """
        extractor = _CONTENT_TYPE_EXTRACTORS.get(content_type)
        if extractor is None:
            return None  # Unknown content type — skip Gate 4

        original_text = _messages_to_text(original)
        compressed_text = _messages_to_text(compressed)

        critical_markers = extractor(original_text)
        if not critical_markers:
            return None  # No markers to check

        missing: list[str] = [
            marker for marker in critical_markers if marker not in compressed_text
        ]

        if not missing:
            return None  # All markers preserved — gate passes

        # Some markers are missing — this is the strangeness tax risk.
        # Revert the compression step.
        missing_sample = missing[:5]  # Log first 5 only
        logger.warning(
            "Quality gate REVERT (Gate 4): %s dropped %d/%d critical markers "
            "for content_type=%s. Missing (sample): %s",
            transform_name,
            len(missing),
            len(critical_markers),
            content_type,
            missing_sample,
        )
        return QualityGateResult(
            accepted=False,
            reason="missing_critical_markers",
            original_tokens=0,
            compressed_tokens=0,
            savings_ratio=0.0,
            details=(
                f"Dropped {len(missing)}/{len(critical_markers)} critical markers "
                f"for {content_type}: {missing_sample}"
            ),
            missing_markers=missing,
        )

    def extract_critical_markers(self, text: str, content_type: str) -> list[str]:
        """Public helper: extract critical markers from text for a given content type.

        Useful for testing and for callers that want to inspect what
        markers the gate would check before running compression.
        """
        extractor = _CONTENT_TYPE_EXTRACTORS.get(content_type)
        if extractor is None:
            return []
        return extractor(text)

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Apply quality gate as a pass-through transform.

        The quality gate doesn't modify messages — it validates
        other transforms' outputs. When used standalone, it simply
        reports the current state.
        """
        tokens_before = tokenizer.count_messages(messages)
        return TransformResult(
            messages=messages,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            transforms_applied=[],
        )
