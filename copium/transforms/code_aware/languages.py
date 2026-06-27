"""Language-specific compression strategies.

Each language strategy knows how to identify and compress language-specific
constructs (docstrings, comments, type annotations, etc.) at different
importance levels.

This surpasses ContextCrumb's single-model approach by applying
language-aware heuristics that understand syntax semantics.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .classifier import ImportanceLevel


@dataclass
class CompressedElement:
    """A compressed code element with metadata."""

    original: str
    compressed: str
    importance: ImportanceLevel
    element_type: str  # "docstring", "comment", "body", "import", etc.
    tokens_saved: int = 0


@dataclass
class LanguageCompressionResult:
    """Result from a language-specific compression pass."""

    output: str
    elements: list[CompressedElement] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.tokens_before == 0:
            return 1.0
        return self.tokens_after / self.tokens_before


class LanguageStrategy(ABC):
    """Base class for language-specific compression strategies."""

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Language identifier."""
        ...

    @abstractmethod
    def compress_docstring(self, docstring: str, level: ImportanceLevel) -> str:
        """Compress a docstring based on importance level."""
        ...

    @abstractmethod
    def compress_comment(self, comment: str, level: ImportanceLevel) -> str:
        """Compress a comment based on importance level."""
        ...

    @abstractmethod
    def compress_body(self, body: str, signature: str, level: ImportanceLevel) -> str:
        """Compress a function/method body."""
        ...

    def compress_imports(self, imports: list[str], level: ImportanceLevel) -> list[str]:
        """Compress import statements. Default: keep all."""
        if level >= ImportanceLevel.HIGH:
            return imports
        # For medium/low, deduplicate and sort
        seen: set[str] = set()
        result = []
        for imp in imports:
            normalized = imp.strip()
            if normalized not in seen:
                seen.add(normalized)
                result.append(imp)
        return result


class PythonStrategy(LanguageStrategy):
    """Python-specific compression strategies."""

    @property
    def language_name(self) -> str:
        return "python"

    def compress_docstring(self, docstring: str, level: ImportanceLevel) -> str:
        """Compress Python docstrings."""
        if level >= ImportanceLevel.CRITICAL:
            return docstring

        lines = docstring.strip().split("\n")
        if not lines:
            return docstring

        if level >= ImportanceLevel.HIGH:
            # Keep first line only
            first_line = lines[0].strip().strip('"""').strip("'''").strip()
            if first_line:
                return f'"""{first_line}"""'
            return docstring

        if level >= ImportanceLevel.MEDIUM:
            # Keep first line + param count hint
            first_line = lines[0].strip().strip('"""').strip("'''").strip()
            param_count = sum(1 for l in lines if ":param" in l or "Args:" in l)
            if param_count:
                return f'"""{first_line} ({param_count} params documented)"""'
            return f'"""{first_line}"""'

        # LOW: Remove entirely
        return ""

    def compress_comment(self, comment: str, level: ImportanceLevel) -> str:
        """Compress Python comments."""
        if level >= ImportanceLevel.HIGH:
            return comment

        if level >= ImportanceLevel.MEDIUM:
            # Keep only non-trivial comments
            stripped = comment.strip().lstrip("#").strip()
            trivial_patterns = [
                r"^-+$",  # separator lines
                r"^=+$",
                r"^\s*$",
                r"^(TODO|FIXME|HACK|XXX)",
            ]
            for pattern in trivial_patterns:
                if re.match(pattern, stripped):
                    return ""
            return comment

        # LOW: Remove all comments
        return ""

    def compress_body(self, body: str, signature: str, level: ImportanceLevel) -> str:
        """Compress Python function body."""
        if level >= ImportanceLevel.CRITICAL:
            return body

        lines = body.split("\n")
        non_empty = [l for l in lines if l.strip()]

        if level >= ImportanceLevel.HIGH:
            # Keep first 5 significant lines + summary
            if len(non_empty) <= 5:
                return body
            kept = non_empty[:5]
            return "\n".join(kept) + f"\n    # ... ({len(non_empty) - 5} more lines)"

        if level >= ImportanceLevel.MEDIUM:
            # Keep only return statements and key logic
            key_lines = [
                l for l in non_empty
                if any(kw in l for kw in ("return", "yield", "raise", "await"))
            ]
            if key_lines:
                return "\n".join(key_lines[:3]) + "\n    # ... (body compressed)"
            return "    # ... (body compressed)"

        # LOW: Just a placeholder
        return "    ..."


class JavaScriptStrategy(LanguageStrategy):
    """JavaScript/TypeScript-specific compression strategies."""

    @property
    def language_name(self) -> str:
        return "javascript"

    def compress_docstring(self, docstring: str, level: ImportanceLevel) -> str:
        """Compress JSDoc comments."""
        if level >= ImportanceLevel.CRITICAL:
            return docstring

        lines = docstring.strip().split("\n")

        if level >= ImportanceLevel.HIGH:
            # Keep @description or first line
            desc_lines = [l for l in lines if "@description" in l or (lines.index(l) == 1 and "/**" in lines[0])]
            if desc_lines:
                return f"/** {desc_lines[0].strip().lstrip('* @description').strip()} */"
            # First meaningful line after /**
            for line in lines[1:]:
                stripped = line.strip().lstrip("* ").strip()
                if stripped and not stripped.startswith("@"):
                    return f"/** {stripped} */"
            return docstring

        if level >= ImportanceLevel.MEDIUM:
            # Count params
            param_count = sum(1 for l in lines if "@param" in l)
            returns = any("@returns" in l or "@return" in l for l in lines)
            parts = []
            if param_count:
                parts.append(f"{param_count} params")
            if returns:
                parts.append("returns")
            if parts:
                return f"/** ({', '.join(parts)}) */"
            return ""

        return ""

    def compress_comment(self, comment: str, level: ImportanceLevel) -> str:
        """Compress JS comments."""
        if level >= ImportanceLevel.HIGH:
            return comment
        if level >= ImportanceLevel.MEDIUM:
            stripped = comment.strip().lstrip("//").strip()
            if len(stripped) > 60:
                return ""  # Remove long comments
            return comment
        return ""

    def compress_body(self, body: str, signature: str, level: ImportanceLevel) -> str:
        """Compress JS function body."""
        if level >= ImportanceLevel.CRITICAL:
            return body

        lines = body.split("\n")
        non_empty = [l for l in lines if l.strip()]

        if level >= ImportanceLevel.HIGH:
            if len(non_empty) <= 5:
                return body
            kept = non_empty[:5]
            return "\n".join(kept) + f"\n  // ... ({len(non_empty) - 5} more lines)"

        if level >= ImportanceLevel.MEDIUM:
            key_lines = [
                l for l in non_empty
                if any(kw in l for kw in ("return", "throw", "await", "yield"))
            ]
            if key_lines:
                return "\n".join(key_lines[:3]) + "\n  // ... (body compressed)"
            return "  // ... (body compressed)"

        return "  // ..."


class RustStrategy(LanguageStrategy):
    """Rust-specific compression strategies."""

    @property
    def language_name(self) -> str:
        return "rust"

    def compress_docstring(self, docstring: str, level: ImportanceLevel) -> str:
        """Compress Rust doc comments (/// or //!)."""
        if level >= ImportanceLevel.CRITICAL:
            return docstring

        lines = docstring.strip().split("\n")

        if level >= ImportanceLevel.HIGH:
            # Keep first doc line
            for line in lines:
                stripped = line.strip().lstrip("/").lstrip("!").strip()
                if stripped:
                    return f"/// {stripped}"
            return docstring

        if level >= ImportanceLevel.MEDIUM:
            # Just a hint
            example_count = sum(1 for l in lines if "```" in l) // 2
            if example_count:
                return f"/// ... ({example_count} examples)"
            return "/// ..."

        return ""

    def compress_comment(self, comment: str, level: ImportanceLevel) -> str:
        """Compress Rust comments."""
        if level >= ImportanceLevel.HIGH:
            return comment
        if level >= ImportanceLevel.MEDIUM:
            # Keep safety comments
            if "SAFETY" in comment.upper() or "INVARIANT" in comment.upper():
                return comment
            return ""
        return ""

    def compress_body(self, body: str, signature: str, level: ImportanceLevel) -> str:
        """Compress Rust function body."""
        if level >= ImportanceLevel.CRITICAL:
            return body

        lines = body.split("\n")
        non_empty = [l for l in lines if l.strip()]

        if level >= ImportanceLevel.HIGH:
            if len(non_empty) <= 5:
                return body
            kept = non_empty[:5]
            return "\n".join(kept) + f"\n    // ... ({len(non_empty) - 5} more lines)"

        if level >= ImportanceLevel.MEDIUM:
            key_lines = [
                l for l in non_empty
                if any(kw in l for kw in ("return", "?;", "panic!", "unwrap", "expect"))
            ]
            if key_lines:
                return "\n".join(key_lines[:3]) + "\n    // ... (body compressed)"
            return "    // ... (body compressed)"

        return "    todo!()"


class GenericStrategy(LanguageStrategy):
    """Fallback strategy for unsupported languages."""

    @property
    def language_name(self) -> str:
        return "generic"

    def compress_docstring(self, docstring: str, level: ImportanceLevel) -> str:
        if level >= ImportanceLevel.HIGH:
            return docstring
        lines = docstring.strip().split("\n")
        if lines:
            return lines[0]
        return ""

    def compress_comment(self, comment: str, level: ImportanceLevel) -> str:
        if level >= ImportanceLevel.HIGH:
            return comment
        if level >= ImportanceLevel.MEDIUM:
            if len(comment.strip()) > 80:
                return ""
            return comment
        return ""

    def compress_body(self, body: str, signature: str, level: ImportanceLevel) -> str:
        if level >= ImportanceLevel.CRITICAL:
            return body
        lines = body.split("\n")
        non_empty = [l for l in lines if l.strip()]
        if level >= ImportanceLevel.HIGH:
            if len(non_empty) <= 5:
                return body
            return "\n".join(non_empty[:5]) + "\n// ... (compressed)"
        if level >= ImportanceLevel.MEDIUM:
            return "// ... (body compressed)"
        return "..."


def get_strategy(language: str) -> LanguageStrategy:
    """Get the appropriate language strategy.

    Args:
        language: Language name (python, javascript, typescript, rust, etc.)

    Returns:
        Language-specific strategy instance.
    """
    _strategies: dict[str, LanguageStrategy] = {
        "python": PythonStrategy(),
        "javascript": JavaScriptStrategy(),
        "typescript": JavaScriptStrategy(),  # TS uses same strategy as JS
        "rust": RustStrategy(),
    }
    return _strategies.get(language, GenericStrategy())
