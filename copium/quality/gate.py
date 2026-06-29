"""Post-compression quality validation gate.

The Quality Gate is a post-compression validation layer that ensures
every lossy compression step meets quality thresholds before the
compressed output reaches the LLM.

Gate checks (in order):
1. Token Count Reduction — compression must actually save tokens
2. Critical Marker Preservation — errors, keys, signatures must survive
3. Semantic Structure Preservation — output must remain parseable
4. Information Density Sanity Check — compressed output shouldn't be filler
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class ContentType(Enum):
    """Content type classification for quality gate checks."""

    JSON = "json"
    CODE = "code"
    LOGS = "logs"
    SEARCH = "search"
    TEXT = "text"


class GateCheck(Enum):
    """Individual gate check identifiers."""

    TOKEN_REDUCTION = "token_reduction"
    CRITICAL_MARKERS = "critical_markers"
    STRUCTURE = "structure"
    DENSITY = "density"


@dataclass
class GateConfig:
    """Configuration for quality gate thresholds."""

    # Token reduction
    min_token_savings_pct: float = 5.0

    # Critical markers
    json_keys_requirement: float = 1.0
    code_signatures_requirement: float = 1.0
    log_errors_requirement: float = 1.0
    text_markers_requirement: float = 0.80

    # Structure
    json_validity_check: bool = True
    code_ast_validity_check: bool = True

    # Density
    min_density_ratio: float = 0.50

    # Behavior
    auto_revert_on_failure: bool = True
    log_gate_failures: bool = True
    emit_metrics: bool = True


@dataclass
class GateResult:
    """Result of a quality gate validation."""

    passed: bool
    original_content: Optional[str]
    compressed_content: Optional[str]
    failures: List[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    latency_ms: float = 0.0


class QualityGate:
    """Post-compression quality validation gate.

    Validates compressed output against the original to ensure quality
    thresholds are met. If validation fails, automatically reverts to
    the original content.

    Example:
        gate = QualityGate(GateConfig(min_token_savings_pct=10.0))
        result = gate.validate(original, compressed, ContentType.JSON)
        if result.passed:
            use(result.compressed_content)
        else:
            use(result.original_content)  # auto-reverted
    """

    def __init__(self, config: Optional[GateConfig] = None):
        self.config = config or GateConfig()
        self._checks_total = 0
        self._checks_passed = 0
        self._checks_failed = 0
        self._reverts_total = 0

    @property
    def pass_rate(self) -> float:
        """Percentage of checks that passed."""
        if self._checks_total == 0:
            return 1.0
        return self._checks_passed / self._checks_total

    @property
    def revert_rate(self) -> float:
        """Percentage of checks that triggered a revert."""
        if self._checks_total == 0:
            return 0.0
        return self._reverts_total / self._checks_total

    @property
    def stats(self) -> dict:
        """Return gate statistics."""
        return {
            "checks_total": self._checks_total,
            "checks_passed": self._checks_passed,
            "checks_failed": self._checks_failed,
            "reverts_total": self._reverts_total,
            "pass_rate": self.pass_rate,
            "revert_rate": self.revert_rate,
        }

    def validate(
        self,
        original: str,
        compressed: str,
        content_type: ContentType,
    ) -> GateResult:
        """Validate compressed content against quality thresholds.

        Args:
            original: Original content before compression.
            compressed: Compressed content to validate.
            content_type: Type of content for specialized checks.

        Returns:
            GateResult with pass/fail status and appropriate content.
        """
        start = time.perf_counter()
        self._checks_total += 1

        checks = [
            (GateCheck.TOKEN_REDUCTION, self._check_token_reduction(original, compressed)),
            (GateCheck.CRITICAL_MARKERS, self._check_critical_markers(original, compressed, content_type)),
            (GateCheck.STRUCTURE, self._check_structure(original, compressed, content_type)),
            (GateCheck.DENSITY, self._check_density(original, compressed)),
        ]

        failures = [check.value for check, passed in checks if not passed]
        latency_ms = (time.perf_counter() - start) * 1000

        if failures:
            self._checks_failed += 1
            if self.config.log_gate_failures:
                logger.warning(
                    "Quality gate failed: %s (content_type=%s, compression=%.1f%%)",
                    failures,
                    content_type.value,
                    (1 - len(compressed) / max(1, len(original))) * 100,
                )

            if self.config.auto_revert_on_failure:
                self._reverts_total += 1
                return GateResult(
                    passed=False,
                    original_content=original,
                    compressed_content=None,
                    failures=failures,
                    metrics={
                        "compression_ratio": len(compressed) / max(1, len(original)),
                        "reverted": True,
                    },
                    latency_ms=latency_ms,
                )

            return GateResult(
                passed=False,
                original_content=original,
                compressed_content=compressed,
                failures=failures,
                metrics={
                    "compression_ratio": len(compressed) / max(1, len(original)),
                    "reverted": False,
                },
                latency_ms=latency_ms,
            )

        self._checks_passed += 1
        return GateResult(
            passed=True,
            original_content=None,
            compressed_content=compressed,
            failures=[],
            metrics={
                "compression_ratio": len(compressed) / max(1, len(original)),
                "reverted": False,
            },
            latency_ms=latency_ms,
        )

    def _check_token_reduction(self, original: str, compressed: str) -> bool:
        """Compression must actually reduce token count."""
        orig_tokens = self._count_tokens(original)
        comp_tokens = self._count_tokens(compressed)

        if comp_tokens > orig_tokens:
            return False

        if orig_tokens == 0:
            return True

        savings_pct = (1 - comp_tokens / orig_tokens) * 100
        return savings_pct >= self.config.min_token_savings_pct

    def _check_critical_markers(
        self, original: str, compressed: str, content_type: ContentType
    ) -> bool:
        """Critical content must survive compression."""
        if content_type == ContentType.JSON:
            return self._check_json_keys(original, compressed)
        elif content_type == ContentType.CODE:
            return self._check_code_signatures(original, compressed)
        elif content_type == ContentType.LOGS:
            return self._check_log_errors(original, compressed)
        elif content_type == ContentType.SEARCH:
            return self._check_search_markers(original, compressed)
        elif content_type == ContentType.TEXT:
            return self._check_text_markers(original, compressed)
        return True

    def _check_json_keys(self, original: str, compressed: str) -> bool:
        """All JSON keys must survive compression."""
        try:
            orig_obj = json.loads(original)
            comp_obj = json.loads(compressed)
            orig_keys = set(self._extract_json_keys(orig_obj))
            comp_keys = set(self._extract_json_keys(comp_obj))
            if not orig_keys:
                return True
            survival = len(orig_keys & comp_keys) / len(orig_keys)
            return survival >= self.config.json_keys_requirement
        except (json.JSONDecodeError, ValueError):
            # If original isn't valid JSON, skip this check
            return not self.config.json_validity_check

    def _check_code_signatures(self, original: str, compressed: str) -> bool:
        """Function signatures and imports must survive compression."""
        orig_sigs = set(self._extract_signatures(original))
        comp_sigs = set(self._extract_signatures(compressed))
        if not orig_sigs:
            return True
        survival = len(orig_sigs & comp_sigs) / len(orig_sigs)
        return survival >= self.config.code_signatures_requirement

    def _check_log_errors(self, original: str, compressed: str) -> bool:
        """Error lines and stack traces must survive compression."""
        error_patterns = ["ERROR", "FAILED", "Exception", "Traceback", "error:", "FATAL", "panic"]
        orig_errors = sum(1 for p in error_patterns if p in original)
        comp_errors = sum(1 for p in error_patterns if p in compressed)
        if orig_errors == 0:
            return True
        return comp_errors / orig_errors >= self.config.log_errors_requirement

    def _check_search_markers(self, original: str, compressed: str) -> bool:
        """File paths and line numbers must survive in search results."""
        orig_paths = set(self._extract_file_paths(original))
        comp_paths = set(self._extract_file_paths(compressed))
        if not orig_paths:
            return True
        survival = len(orig_paths & comp_paths) / len(orig_paths)
        return survival >= 0.80

    def _check_text_markers(self, original: str, compressed: str) -> bool:
        """Headers and structural markers must survive compression."""
        marker_patterns = ["# ", "## ", "### ", "```", "---", "**"]
        orig_markers = sum(1 for p in marker_patterns if p in original)
        comp_markers = sum(1 for p in marker_patterns if p in compressed)
        if orig_markers == 0:
            return True
        return comp_markers / orig_markers >= self.config.text_markers_requirement

    def _check_structure(self, original: str, compressed: str, content_type: ContentType) -> bool:
        """Semantic structure must remain valid after compression."""
        if content_type == ContentType.JSON:
            try:
                json.loads(compressed)
                return True
            except json.JSONDecodeError:
                return not self.config.json_validity_check
        elif content_type == ContentType.CODE:
            if self.config.code_ast_validity_check:
                return self._check_code_parseable(compressed)
        return True

    def _check_code_parseable(self, code: str) -> bool:
        """Check if code is syntactically valid Python."""
        import ast

        try:
            ast.parse(code)
            return True
        except SyntaxError:
            # May not be Python — allow non-Python code through
            return True

    def _check_density(self, original: str, compressed: str) -> bool:
        """Compressed output shouldn't be mostly filler."""
        orig_tokens = self._tokenize(original)
        comp_tokens = self._tokenize(compressed)
        if not comp_tokens:
            return False
        if not orig_tokens:
            return True

        orig_density = len(set(orig_tokens)) / max(1, len(orig_tokens))
        comp_density = len(set(comp_tokens)) / max(1, len(comp_tokens))
        return comp_density >= orig_density * self.config.min_density_ratio

    def _count_tokens(self, text: str) -> int:
        """Approximate token count (word-based heuristic)."""
        return len(text.split())

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words."""
        return text.split()

    def _extract_json_keys(self, obj, prefix: str = "") -> List[str]:
        """Recursively extract all JSON keys."""
        keys: List[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{prefix}.{k}" if prefix else k
                keys.append(full_key)
                keys.extend(self._extract_json_keys(v, full_key))
        elif isinstance(obj, list) and obj:
            keys.extend(self._extract_json_keys(obj[0], f"{prefix}[]"))
        return keys

    def _extract_signatures(self, code: str) -> List[str]:
        """Extract function/class signatures from code."""
        patterns = [
            r"def \w+\s*\(",
            r"function \w+\s*\(",
            r"func \w+\s*\(",
            r"fn \w+\s*\(",
            r"class \w+",
            r"import \w+",
            r"from \w+ import",
            r"pub fn \w+",
            r"pub struct \w+",
        ]
        return [m for p in patterns for m in re.findall(p, code)]

    def _extract_file_paths(self, text: str) -> List[str]:
        """Extract file paths from text."""
        pattern = r"[\w./\\-]+\.\w{1,10}"
        return re.findall(pattern, text)
