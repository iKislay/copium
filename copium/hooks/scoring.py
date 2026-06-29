"""Entropy-based message scoring for compression priority.

Scores messages by information density to determine compression priority.
Messages with higher entropy (more unique, irreplaceable information) get
lower compression bias — they are preserved more aggressively.

This module provides the scoring engine used by InputPriorityHooks and
can be used standalone for compression scheduling decisions.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass
class MessageScore:
    """Scoring result for a single message."""

    index: int
    role: str
    entropy: float  # 0.0 to 1.0 normalized
    uniqueness: float  # 0.0 to 1.0 — how unique vs. repetitive
    token_estimate: int
    compressibility: float  # 0.0 to 1.0 — how compressible (high = easy to compress)

    @property
    def preservation_priority(self) -> float:
        """Priority for preservation (0.0 = compress first, 1.0 = preserve).

        Combines entropy, uniqueness, and role-based priority.
        """
        role_weight = {"user": 0.9, "assistant": 0.5, "tool": 0.3, "system": 0.95}
        base = role_weight.get(self.role, 0.5)
        return base * 0.5 + self.entropy * 0.3 + self.uniqueness * 0.2

    @property
    def compression_bias(self) -> float:
        """Compute compression bias from preservation priority.

        Lower value = preserve more (compress less aggressively).
        """
        # Map priority [0, 1] to bias [0.2, 2.0]
        return 0.2 + (1.0 - self.preservation_priority) * 1.8


class MessageEntropyScorer:
    """Score messages by their information entropy for compression scheduling.

    Uses multiple signals:
    1. Character n-gram entropy (Shannon entropy)
    2. Uniqueness relative to other messages in the conversation
    3. Token count estimation
    4. Role-based priors
    """

    def __init__(
        self,
        ngram_size: int = 3,
        chars_per_token: float = 4.0,
    ):
        self.ngram_size = ngram_size
        self.chars_per_token = chars_per_token

    def score_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[MessageScore]:
        """Score all messages in a conversation.

        Returns scores ordered by message index.
        """
        # First pass: extract text content
        texts = [self._extract_text(msg) for msg in messages]

        # Compute pairwise uniqueness using shingle overlap
        shingle_sets = [self._shingle_set(t) for t in texts]

        scores: list[MessageScore] = []
        for i, (msg, text) in enumerate(zip(messages, texts)):
            entropy = self._compute_entropy(text)
            uniqueness = self._compute_uniqueness(i, shingle_sets)
            token_est = max(1, int(len(text) / self.chars_per_token))
            compressibility = self._estimate_compressibility(text, msg.get("role", ""))

            scores.append(
                MessageScore(
                    index=i,
                    role=msg.get("role", "unknown"),
                    entropy=entropy,
                    uniqueness=uniqueness,
                    token_estimate=token_est,
                    compressibility=compressibility,
                )
            )

        return scores

    def compute_biases(
        self, messages: list[dict[str, Any]]
    ) -> dict[int, float]:
        """Compute per-message compression biases from entropy scores.

        Returns dict of {message_index: bias}. Lower bias = preserve more.
        """
        scores = self.score_messages(messages)
        return {s.index: s.compression_bias for s in scores}

    def _extract_text(self, message: dict[str, Any]) -> str:
        """Extract text content from a message dict."""
        content = message.get("content", "")
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict):
                    parts.append(p.get("text", ""))
                else:
                    parts.append(str(p))
            return " ".join(parts)
        return str(content)

    def _compute_entropy(self, text: str) -> float:
        """Compute normalized Shannon entropy of character n-grams."""
        if not text or len(text) < self.ngram_size:
            return 0.0

        ngrams = [
            text[i : i + self.ngram_size]
            for i in range(len(text) - self.ngram_size + 1)
        ]

        counts = Counter(ngrams)
        total = len(ngrams)

        entropy = 0.0
        for count in counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        max_entropy = math.log2(min(total, 256**self.ngram_size))
        if max_entropy == 0:
            return 0.0

        return min(entropy / max_entropy, 1.0)

    def _shingle_set(self, text: str, k: int = 5) -> set[str]:
        """Get set of k-shingles for Jaccard uniqueness."""
        if len(text) < k:
            return {text} if text else set()
        return {text[i : i + k] for i in range(len(text) - k + 1)}

    def _compute_uniqueness(
        self, index: int, shingle_sets: list[set[str]]
    ) -> float:
        """Compute uniqueness of message relative to others.

        Uses average Jaccard distance to all other messages.
        """
        if not shingle_sets[index]:
            return 0.0

        distances: list[float] = []
        for j, other in enumerate(shingle_sets):
            if j == index or not other:
                continue
            intersection = len(shingle_sets[index] & other)
            union = len(shingle_sets[index] | other)
            if union > 0:
                jaccard = intersection / union
                distances.append(1.0 - jaccard)  # distance = 1 - similarity

        if not distances:
            return 1.0  # Only message — maximally unique

        return sum(distances) / len(distances)

    def _estimate_compressibility(self, text: str, role: str) -> float:
        """Estimate how compressible a message is.

        Higher = easier to compress (more repetitive/structured content).
        """
        if not text:
            return 1.0

        # Role-based priors
        role_compressibility = {
            "tool": 0.8,  # Tool outputs are usually repetitive
            "assistant": 0.6,  # Model outputs follow patterns
            "user": 0.3,  # User input is harder to compress
            "system": 0.2,  # System prompts are critical
        }
        base = role_compressibility.get(role, 0.5)

        # Check for structural patterns that indicate compressibility
        line_count = text.count("\n") + 1
        if line_count > 20:
            # Many lines → likely structured output → more compressible
            base = min(base + 0.2, 1.0)

        # Check for repeated patterns
        lines = text.split("\n")
        if lines:
            unique_lines = len(set(lines))
            repetition_ratio = 1.0 - (unique_lines / len(lines))
            base = min(base + repetition_ratio * 0.3, 1.0)

        return base
