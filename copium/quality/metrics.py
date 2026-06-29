"""Quality metrics for compression evaluation.

Provides ROUGE-L, BERTScore approximation, Information Preservation
Score (IPS), and Compression-Weighted Quality (CWQ) calculations.

These metrics quantify how well compression preserves the information
the LLM needs to produce correct answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass
class MetricsResult:
    """Result of quality metrics computation."""

    rouge_l: float
    info_preservation_score: float
    compression_weighted_quality: float
    compression_ratio: float
    token_savings: int
    error_preservation: float
    structure_preservation: float
    key_value_preservation: float


class QualityMetrics:
    """Compute quality metrics for compressed vs original content.

    Metrics:
    - ROUGE-L: Longest common subsequence overlap (target >= 0.85)
    - IPS: Information Preservation Score (target >= 0.95)
    - CWQ: Compression-Weighted Quality (target >= 0.85)

    Example:
        metrics = QualityMetrics()
        result = metrics.compute(original, compressed)
        assert result.rouge_l >= 0.85
        assert result.info_preservation_score >= 0.95
    """

    def __init__(self, beta: float = 1.25):
        self._beta = beta

    def compute(
        self,
        original: str,
        compressed: str,
        task_accuracy: Optional[float] = None,
    ) -> MetricsResult:
        """Compute all quality metrics.

        Args:
            original: Original content before compression.
            compressed: Compressed content.
            task_accuracy: Optional end-to-end task accuracy ratio.

        Returns:
            MetricsResult with all computed metrics.
        """
        rouge_l = self.rouge_l(original, compressed)
        error_pres = self._error_preservation(original, compressed)
        struct_pres = self._structure_preservation(original, compressed)
        kv_pres = self._key_value_preservation(original, compressed)

        ips = self._compute_ips(error_pres, struct_pres, kv_pres)

        orig_tokens = len(original.split())
        comp_tokens = len(compressed.split())
        compression_ratio = 1 - (comp_tokens / max(1, orig_tokens))
        token_savings = orig_tokens - comp_tokens

        accuracy = task_accuracy if task_accuracy is not None else 1.0
        cwq = compression_ratio * accuracy

        return MetricsResult(
            rouge_l=rouge_l,
            info_preservation_score=ips,
            compression_weighted_quality=cwq,
            compression_ratio=compression_ratio,
            token_savings=token_savings,
            error_preservation=error_pres,
            structure_preservation=struct_pres,
            key_value_preservation=kv_pres,
        )

    def rouge_l(self, reference: str, hypothesis: str) -> float:
        """Compute ROUGE-L score between reference and hypothesis.

        Uses longest common subsequence (LCS) with beta=1.25 to
        favor recall over precision (preserving information matters
        more than brevity).
        """
        ref_tokens = reference.split()
        hyp_tokens = hypothesis.split()

        if not ref_tokens or not hyp_tokens:
            return 0.0

        lcs_len = self._lcs_length(ref_tokens, hyp_tokens)

        precision = lcs_len / len(hyp_tokens) if hyp_tokens else 0.0
        recall = lcs_len / len(ref_tokens) if ref_tokens else 0.0

        if precision == 0.0 and recall == 0.0:
            return 0.0

        beta_sq = self._beta ** 2
        f_score = (1 + beta_sq) * (precision * recall) / (beta_sq * precision + recall)
        return f_score

    def _lcs_length(self, seq1: Sequence[str], seq2: Sequence[str]) -> int:
        """Compute length of longest common subsequence."""
        m, n = len(seq1), len(seq2)

        # Use O(min(m,n)) space
        if m < n:
            seq1, seq2 = seq2, seq1
            m, n = n, m

        prev = [0] * (n + 1)
        curr = [0] * (n + 1)

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if seq1[i - 1] == seq2[j - 1]:
                    curr[j] = prev[j - 1] + 1
                else:
                    curr[j] = max(prev[j], curr[j - 1])
            prev, curr = curr, [0] * (n + 1)

        return prev[n]

    def _error_preservation(self, original: str, compressed: str) -> float:
        """Measure how well error indicators are preserved."""
        error_indicators = [
            "ERROR", "Error", "error", "FAILED", "Failed",
            "Exception", "Traceback", "FATAL", "panic",
            "stack trace", "at line", "exit code",
        ]
        orig_count = sum(1 for e in error_indicators if e in original)
        if orig_count == 0:
            return 1.0
        comp_count = sum(1 for e in error_indicators if e in compressed)
        return min(1.0, comp_count / orig_count)

    def _structure_preservation(self, original: str, compressed: str) -> float:
        """Measure how well structural elements are preserved."""
        structural = [
            "{", "}", "[", "]",
            "def ", "class ", "function ", "import ",
            "# ", "## ", "### ",
        ]
        orig_count = sum(original.count(s) for s in structural)
        if orig_count == 0:
            return 1.0
        comp_count = sum(compressed.count(s) for s in structural)
        return min(1.0, comp_count / orig_count)

    def _key_value_preservation(self, original: str, compressed: str) -> float:
        """Measure how well key values (UUIDs, hashes, IDs) are preserved."""
        import re

        # Match UUIDs, hex hashes, and numeric IDs
        patterns = [
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            r"[0-9a-f]{32,64}",
            r"\b\d{5,}\b",
        ]

        orig_values: set = set()
        comp_values: set = set()

        for pattern in patterns:
            orig_values.update(re.findall(pattern, original, re.IGNORECASE))
            comp_values.update(re.findall(pattern, compressed, re.IGNORECASE))

        if not orig_values:
            return 1.0

        preserved = len(orig_values & comp_values)
        return preserved / len(orig_values)

    def _compute_ips(
        self,
        error_pres: float,
        struct_pres: float,
        kv_pres: float,
    ) -> float:
        """Compute Information Preservation Score.

        IPS = w1*error + w2*structure + w3*key_values
        Where w1=0.4, w2=0.3, w3=0.3
        """
        return 0.4 * error_pres + 0.3 * struct_pres + 0.3 * kv_pres


def compute_rouge_l_batch(
    references: List[str],
    hypotheses: List[str],
    beta: float = 1.25,
) -> List[float]:
    """Compute ROUGE-L scores for a batch of reference/hypothesis pairs."""
    metrics = QualityMetrics(beta=beta)
    return [metrics.rouge_l(ref, hyp) for ref, hyp in zip(references, hypotheses)]
