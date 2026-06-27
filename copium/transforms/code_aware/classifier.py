"""Token/symbol importance classification for code compression.

Classifies code elements by importance level to enable differential
compression - critical elements get lossless treatment while low-importance
elements can be aggressively compressed or removed.

This is a key differentiator vs ContextCrumb which treats all tokens equally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ImportanceLevel(IntEnum):
    """Importance levels for code elements.

    Higher = more important = less compression applied.
    """

    CRITICAL = 4  # Must never be compressed (executable code, error handlers)
    HIGH = 3  # Should be preserved with minimal compression (signatures, types)
    MEDIUM = 2  # Can be moderately compressed (comments, docstrings)
    LOW = 1  # Can be aggressively compressed or removed (whitespace, verbose logs)


@dataclass
class SymbolImportance:
    """Importance classification for a single code symbol/element."""

    name: str
    level: ImportanceLevel
    reason: str
    start_line: int = 0
    end_line: int = 0
    token_count: int = 0

    @property
    def compressible(self) -> bool:
        """Whether this element can be compressed."""
        return self.level < ImportanceLevel.CRITICAL


@dataclass
class ClassificationResult:
    """Result of classifying all elements in a code block."""

    symbols: list[SymbolImportance] = field(default_factory=list)
    overall_importance: ImportanceLevel = ImportanceLevel.MEDIUM

    @property
    def critical_count(self) -> int:
        return sum(1 for s in self.symbols if s.level == ImportanceLevel.CRITICAL)

    @property
    def compressible_tokens(self) -> int:
        return sum(s.token_count for s in self.symbols if s.compressible)

    @property
    def total_tokens(self) -> int:
        return sum(s.token_count for s in self.symbols)

    @property
    def compressible_ratio(self) -> float:
        total = self.total_tokens
        if total == 0:
            return 0.0
        return self.compressible_tokens / total


# Patterns that indicate critical code
_CRITICAL_PATTERNS = [
    re.compile(r"\b(raise|throw|assert|panic!?)\b"),
    re.compile(r"\b(try|catch|except|finally|rescue)\b"),
    re.compile(r"\b(if\s+__name__\s*==)\b"),
    re.compile(r"\b(return|yield)\b"),
    re.compile(r"\b(async|await)\b"),
]

# Patterns for high-importance elements
_HIGH_PATTERNS = [
    re.compile(r"^\s*(def|fn|func|function)\s+\w+"),
    re.compile(r"^\s*(class|struct|enum|interface|trait|impl)\s+\w+"),
    re.compile(r"^\s*(import|from|use|require|include)\s+"),
    re.compile(r"^\s*@\w+"),  # decorators
    re.compile(r":\s*(str|int|float|bool|List|Dict|Optional|Any|Result)\b"),  # type annotations
]

# Patterns for low-importance elements
_LOW_PATTERNS = [
    re.compile(r"^\s*#\s*(TODO|FIXME|HACK|XXX|NOTE)", re.IGNORECASE),
    re.compile(r"^\s*(console\.log|print|debug|logger\.(debug|trace))"),
    re.compile(r"^\s*pass\s*$"),
    re.compile(r"^\s*\.\.\.\s*$"),  # ellipsis placeholder
]


class ImportanceClassifier:
    """Classifies code elements by importance for differential compression.

    This is the core intelligence that ContextCrumb lacks - instead of
    treating all tokens equally, we classify by structural role and apply
    appropriate compression per importance level.
    """

    def __init__(
        self,
        *,
        custom_critical_patterns: list[re.Pattern[str]] | None = None,
        custom_low_patterns: list[re.Pattern[str]] | None = None,
        reference_weight: float = 0.3,
        structural_weight: float = 0.4,
        pattern_weight: float = 0.3,
    ):
        """Initialize classifier.

        Args:
            custom_critical_patterns: Additional patterns to mark as critical.
            custom_low_patterns: Additional patterns to mark as low-importance.
            reference_weight: Weight for reference-count scoring.
            structural_weight: Weight for structural role scoring.
            pattern_weight: Weight for pattern-match scoring.
        """
        self._critical_patterns = list(_CRITICAL_PATTERNS)
        if custom_critical_patterns:
            self._critical_patterns.extend(custom_critical_patterns)

        self._low_patterns = list(_LOW_PATTERNS)
        if custom_low_patterns:
            self._low_patterns.extend(custom_low_patterns)

        self._reference_weight = reference_weight
        self._structural_weight = structural_weight
        self._pattern_weight = pattern_weight

    def classify_line(self, line: str) -> ImportanceLevel:
        """Classify a single line of code by importance.

        Args:
            line: Single line of source code.

        Returns:
            Importance level for this line.
        """
        stripped = line.strip()
        if not stripped:
            return ImportanceLevel.LOW

        # Check critical patterns
        for pattern in self._critical_patterns:
            if pattern.search(stripped):
                return ImportanceLevel.CRITICAL

        # Check high-importance patterns
        for pattern in _HIGH_PATTERNS:
            if pattern.search(stripped):
                return ImportanceLevel.HIGH

        # Check low-importance patterns
        for pattern in self._low_patterns:
            if pattern.search(stripped):
                return ImportanceLevel.LOW

        return ImportanceLevel.MEDIUM

    def classify_block(
        self,
        code: str,
        *,
        symbol_name: str = "",
        references: int = 0,
        is_exported: bool = False,
        is_test: bool = False,
    ) -> SymbolImportance:
        """Classify a code block (function body, class, etc.).

        Combines multiple signals:
        - Pattern matching (what code patterns appear)
        - Structural role (export, test, etc.)
        - Reference count (how often it's referenced)

        Args:
            code: The code block to classify.
            symbol_name: Name of the symbol (function/class name).
            references: Number of times this symbol is referenced.
            is_exported: Whether this symbol is exported/public.
            is_test: Whether this is a test function.

        Returns:
            SymbolImportance with classified level.
        """
        lines = code.split("\n")
        line_levels = [self.classify_line(line) for line in lines]

        # Pattern-based score (0-1)
        if line_levels:
            pattern_score = max(line_levels) / ImportanceLevel.CRITICAL
        else:
            pattern_score = 0.0

        # Structural score (0-1)
        structural_score = 0.5  # default
        if is_exported:
            structural_score = 0.8
        if is_test:
            structural_score = 0.3  # tests are less critical for context
        if symbol_name.startswith("_"):
            structural_score *= 0.7  # private symbols less important

        # Reference score (0-1), logarithmic scale
        import math
        ref_score = min(1.0, math.log2(references + 1) / 5.0) if references > 0 else 0.2

        # Weighted combination
        combined = (
            self._pattern_weight * pattern_score
            + self._structural_weight * structural_score
            + self._reference_weight * ref_score
        )

        # Map to level
        if combined >= 0.75:
            level = ImportanceLevel.CRITICAL
        elif combined >= 0.55:
            level = ImportanceLevel.HIGH
        elif combined >= 0.3:
            level = ImportanceLevel.MEDIUM
        else:
            level = ImportanceLevel.LOW

        reason = (
            f"pattern={pattern_score:.2f} structural={structural_score:.2f} "
            f"ref={ref_score:.2f} combined={combined:.2f}"
        )

        return SymbolImportance(
            name=symbol_name,
            level=level,
            reason=reason,
            token_count=len(code) // 4,  # approximate
        )

    def classify_ast_nodes(
        self,
        nodes: list[dict[str, Any]],
    ) -> ClassificationResult:
        """Classify a list of AST node descriptions.

        Args:
            nodes: List of dicts with keys: name, code, type, references, exported.

        Returns:
            ClassificationResult with all symbols classified.
        """
        symbols = []
        for node in nodes:
            importance = self.classify_block(
                code=node.get("code", ""),
                symbol_name=node.get("name", ""),
                references=node.get("references", 0),
                is_exported=node.get("exported", False),
                is_test=node.get("name", "").startswith("test_"),
            )
            importance.start_line = node.get("start_line", 0)
            importance.end_line = node.get("end_line", 0)
            symbols.append(importance)

        # Overall importance is the max of all symbols
        overall = ImportanceLevel.MEDIUM
        if symbols:
            overall = ImportanceLevel(max(s.level for s in symbols))

        return ClassificationResult(symbols=symbols, overall_importance=overall)
