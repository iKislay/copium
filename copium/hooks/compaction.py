"""Pre-compaction hook data models and input-priority compression.

Extends the base CompressionHooks with compaction-aware strategies:
- PreCompactHookData: full context available before compaction fires
- PostCompactHookData: results available after compaction completes
- InputPriorityHooks: preserve user messages (high entropy, irreplaceable)
- EntropyScorer: score messages by information entropy for bias computation

Based on community feedback (anthropics/claude-code #34299, #36984, #33088):
user inputs have higher information entropy than model outputs, and should
receive lower compression (higher preservation).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..hooks import CompressContext, CompressEvent, CompressionHooks


@dataclass
class PreCompactHookData:
    """Data available to PreCompact hooks.

    Mirrors the community-requested hook data from GitHub issue #33088.
    """

    context_tokens_before: int
    context_tokens_after_estimate: int
    messages_count: int
    tool_calls_count: int
    compaction_reason: str  # "context_limit" | "manual" | "quality"
    messages: list[dict[str, Any]]
    compressed_content: dict[str, str]  # hash -> content preview
    session_id: str = ""
    model: str = ""

    @property
    def compression_ratio_estimate(self) -> float:
        """Estimated compression ratio."""
        if self.context_tokens_before == 0:
            return 0.0
        return self.context_tokens_after_estimate / self.context_tokens_before


@dataclass
class PostCompactHookData:
    """Data available to PostCompact hooks after compaction completes."""

    context_tokens_after: int
    messages_kept: list[dict[str, Any]]
    messages_compressed: list[str]  # hashes of compressed content
    ccr_references: list[str]  # CCR hash keys for retrieval
    session_id: str = ""
    model: str = ""
    compression_ratio: float = 0.0
    tokens_saved: int = 0


class EntropyScorer:
    """Score messages by information entropy.

    Higher entropy = more irreplaceable = preserve more.
    User messages typically have higher entropy than assistant responses
    because they contain unique intent, constraints, and context.
    """

    def __init__(self, ngram_size: int = 3):
        self.ngram_size = ngram_size

    def score(self, text: str) -> float:
        """Compute normalized entropy score for text (0.0 to 1.0).

        Uses character n-gram entropy as a proxy for information density.
        """
        if not text or len(text) < self.ngram_size:
            return 0.0

        # Extract n-grams
        ngrams = [
            text[i : i + self.ngram_size]
            for i in range(len(text) - self.ngram_size + 1)
        ]

        # Count frequencies
        counts = Counter(ngrams)
        total = len(ngrams)

        # Shannon entropy
        entropy = 0.0
        for count in counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        # Normalize by max possible entropy for the vocabulary size
        max_entropy = math.log2(min(total, 256**self.ngram_size))
        if max_entropy == 0:
            return 0.0

        return min(entropy / max_entropy, 1.0)

    def score_message(self, message: dict[str, Any]) -> float:
        """Score a message dict by its content entropy."""
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
        return self.score(str(content))


class InputPriorityHooks(CompressionHooks):
    """Compression hooks that preserve user messages over tool outputs.

    Based on the insight from GitHub issue #34299:
    'Inputs have higher information entropy than outputs — a user's message
    is unique and unpredictable, while the model's response is largely
    derivable from the input.'

    Bias settings:
    - User messages: 0.3 (preserve 70% more than default)
    - Assistant messages: 1.0 (default compression)
    - Tool outputs: 1.5 (compress 50% more aggressively)

    The entropy scorer further adjusts biases based on actual information
    density of each message.
    """

    def __init__(
        self,
        user_bias: float = 0.3,
        assistant_bias: float = 1.0,
        tool_bias: float = 1.5,
        use_entropy_scoring: bool = True,
        entropy_weight: float = 0.3,
    ):
        self.user_bias = user_bias
        self.assistant_bias = assistant_bias
        self.tool_bias = tool_bias
        self.use_entropy_scoring = use_entropy_scoring
        self.entropy_weight = entropy_weight
        self._scorer = EntropyScorer()

    def compute_biases(
        self,
        messages: list[dict[str, Any]],
        ctx: CompressContext,
    ) -> dict[int, float]:
        """Compute per-message compression biases with input priority.

        Lower bias = preserve more. Higher bias = compress more.
        """
        biases: dict[int, float] = {}

        for i, msg in enumerate(messages):
            role = msg.get("role", "")

            # Base bias by role
            if role == "user":
                base_bias = self.user_bias
            elif role == "assistant":
                base_bias = self.assistant_bias
            elif role == "tool" or msg.get("tool_call_id"):
                base_bias = self.tool_bias
            else:
                base_bias = 1.0

            # Apply entropy adjustment if enabled
            if self.use_entropy_scoring:
                entropy = self._scorer.score_message(msg)
                # Higher entropy → lower bias (preserve more)
                entropy_adjustment = -self.entropy_weight * entropy
                base_bias = max(0.1, base_bias + entropy_adjustment)

            biases[i] = base_bias

        return biases

    def pre_compress(
        self,
        messages: list[dict[str, Any]],
        ctx: CompressContext,
    ) -> list[dict[str, Any]]:
        """Pre-compress pass — no modifications, just pass through."""
        return messages

    def post_compress(self, event: CompressEvent) -> None:
        """Log compression results."""
        pass
