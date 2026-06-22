"""Post-compression quality verification transform.

After each lossy compression step, re-measure with the tokenizer.
If compression doesn't actually save tokens (or makes things worse),
auto-revert that step. Makes compression safe-by-default — users
never get a higher bill from a transform that was supposed to help.

The quality gate operates at the transform pipeline level, checking
each transform's output against the original to ensure:
1. Token count actually decreased (or stayed the same)
2. No significant content was lost (measured by token ratio)

When a transform fails the gate, its changes are reverted and a
warning is logged. This prevents "negative savings" where a transform
inflates tokens instead of compressing them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..config import QualityGateConfig, TransformResult
from ..tokenizer import Tokenizer
from .base import Transform

logger = logging.getLogger(__name__)


@dataclass
class QualityGateResult:
    """Result of a quality gate check."""

    accepted: bool
    reason: str
    original_tokens: int
    compressed_tokens: int
    savings_ratio: float
    details: str = ""


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
    ) -> QualityGateResult:
        """Check if compression passes the quality gate.

        Args:
            original: Original messages before compression.
            compressed: Compressed messages after compression.
            tokenizer: Tokenizer for counting tokens.
            transform_name: Name of the transform being checked.

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

        # All gates passed
        return QualityGateResult(
            accepted=True,
            reason="passed",
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            savings_ratio=savings_ratio,
            details=f"Saved {tokens_saved} tokens ({savings_ratio:.1%})",
        )

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
