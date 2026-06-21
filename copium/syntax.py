"""Syntax-constrained compression.

Ensures compressed output is always valid by using syntax rules to
constrain the compression process. This prevents the compressor from
producing malformed JSON, broken markdown, or truncated code.

Key features:
- JSON syntax enforcement: compressed JSON is always valid
- Markdown syntax enforcement: compressed markdown preserves structure
- Code syntax enforcement: compressed code preserves syntax
- Schema-aware: function calling schemas are compressed without breaking

The syntax validator acts as a safety net — if a lossy compression step
would produce invalid output, the validator catches it and falls back to
a lossless approach.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SyntaxType(Enum):
    """Types of grammar constraints."""

    JSON = "json"
    MARKDOWN = "markdown"
    CODE = "code"
    XML = "xml"
    FREEFORM = "freeform"


@dataclass
class SyntaxRule:
    """A grammar rule for compression validation."""

    grammar_type: SyntaxType
    description: str
    validate: callable  # Returns True if content is valid
    repair: callable | None = None  # Attempt to repair invalid content


# ============================================================================
# JSON Grammar
# ============================================================================

def _validate_json(content: str) -> bool:
    """Validate that content is valid JSON."""
    try:
        json.loads(content)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _repair_json(content: str) -> str:
    """Attempt to repair invalid JSON."""
    # Remove trailing commas before } or ]
    fixed = re.sub(r",\s*([}\]])", r"\1", content)
    # Try parsing again
    try:
        json.loads(fixed)
        return fixed
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find the last valid JSON object/array
    for end in range(len(content), 0, -1):
        try:
            json.loads(content[:end])
            return content[:end]
        except (json.JSONDecodeError, ValueError):
            continue

    # Try adding missing closing brackets
    if stripped := content.strip():
        if stripped.startswith("{"):
            # Try adding closing }
            for suffix in ["}", '"}', '"]}', '"}]']:
                try:
                    json.loads(stripped + suffix)
                    return stripped + suffix
                except (json.JSONDecodeError, ValueError):
                    continue
        elif stripped.startswith("["):
            # Try adding closing ]
            for suffix in ["]", "]", "]]"]:
                try:
                    json.loads(stripped + suffix)
                    return stripped + suffix
                except (json.JSONDecodeError, ValueError):
                    continue

    return content  # Give up, return as-is


JSON_GRAMMAR = SyntaxRule(
    grammar_type=SyntaxType.JSON,
    description="JSON grammar enforcement",
    validate=_validate_json,
    repair=_repair_json,
)


# ============================================================================
# Markdown Grammar
# ============================================================================

def _validate_markdown(content: str) -> bool:
    """Validate that content preserves markdown structure."""
    # Check that headers are intact
    lines = content.split("\n")
    for line in lines:
        # Headers should start with # and have a space
        if re.match(r"^#{1,6}[^ #]", line):
            return False
        # Code blocks should be properly closed
    # Count code block markers
    fence_count = content.count("```")
    if fence_count % 2 != 0:
        return False
    return True


def _repair_markdown(content: str) -> str:
    """Attempt to repair invalid markdown."""
    # Fix headers without space
    content = re.sub(r"^(#{1,6})([^ #])", r"\1 \2", content, flags=re.M)

    # Fix unclosed code blocks
    fence_count = content.count("```")
    if fence_count % 2 != 0:
        content = content.rstrip() + "\n```\n"

    return content


MARKDOWN_GRAMMAR = SyntaxRule(
    grammar_type=SyntaxType.MARKDOWN,
    description="Markdown grammar enforcement",
    validate=_validate_markdown,
    repair=_repair_markdown,
)


# ============================================================================
# Code Grammar (basic syntax checks)
# ============================================================================

def _validate_code(content: str) -> bool:
    """Basic code syntax validation."""
    # Check balanced brackets
    stack = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    in_string = False
    string_char = None
    in_comment = False

    for i, char in enumerate(content):
        # Track string state
        if in_string:
            if char == string_char and (i == 0 or content[i - 1] != "\\"):
                in_string = False
            continue

        if char in ('"', "'", "`"):
            in_string = True
            string_char = char
            continue

        # Track comment state
        if char == "#" and not in_string:
            in_comment = True
            continue
        if char == "\n":
            in_comment = False
            continue
        if in_comment:
            continue

        # Check brackets
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack[-1] != char:
                return False
            stack.pop()

    return len(stack) == 0


def _repair_code(content: str) -> str:
    """Attempt basic code repairs."""
    # Remove trailing incomplete lines
    lines = content.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    # Add closing brackets if needed
    open_count = content.count("{") - content.count("}")
    if open_count > 0:
        content += "\n" + "}" * open_count

    return content


CODE_GRAMMAR = SyntaxRule(
    grammar_type=SyntaxType.CODE,
    description="Code syntax enforcement",
    validate=_validate_code,
    repair=_repair_code,
)


# ============================================================================
# Grammar Registry
# ============================================================================

SYNTAX_RULES: dict[SyntaxType, SyntaxRule] = {
    SyntaxType.JSON: JSON_GRAMMAR,
    SyntaxType.MARKDOWN: MARKDOWN_GRAMMAR,
    SyntaxType.CODE: CODE_GRAMMAR,
}


def detect_syntax(content: str) -> SyntaxType:
    """Auto-detect the grammar type of content."""
    stripped = content.strip()

    # JSON detection (by structure, not just validity)
    if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
        return SyntaxType.JSON

    # Markdown detection
    if re.search(r"^#{1,6}\s", content, re.M) or "```" in content:
        return SyntaxType.MARKDOWN

    # Code detection (heuristic)
    code_signals = [
        "def ", "class ", "import ", "from ", "function ", "const ", "let ",
        "var ", "return ", "if (", "for (", "while (", "public ", "private ",
    ]
    if any(sig in content for sig in code_signals):
        return SyntaxType.CODE

    # XML detection
    if stripped.startswith("<") and stripped.endswith(">"):
        return SyntaxType.XML

    return SyntaxType.FREEFORM


def validate_and_repair(content: str, grammar_type: SyntaxType | None = None) -> tuple[bool, str, SyntaxType]:
    """Validate content against a grammar and repair if needed.

    Returns (is_valid, repaired_content, detected_grammar).
    """
    if grammar_type is None:
        grammar_type = detect_syntax(content)

    if grammar_type == SyntaxType.FREEFORM:
        return True, content, grammar_type

    rule = SYNTAX_RULES.get(grammar_type)
    if rule is None:
        return True, content, grammar_type

    is_valid = rule.validate(content)
    if is_valid:
        return True, content, grammar_type

    # Attempt repair
    if rule.repair:
        repaired = rule.repair(content)
        is_repaired = rule.validate(repaired)
        if is_repaired:
            return True, repaired, grammar_type

    return False, content, grammar_type


@dataclass
class SyntaxCompressorConfig:
    """Configuration for grammar-constrained compression.

    Ensures compressed output is always valid by using grammar rules
    to constrain the compression process. Prevents the compressor from
    producing malformed JSON, broken markdown, or truncated code.
    """

    enabled: bool = True

    # Grammar types to enforce
    enforce_json: bool = True
    enforce_markdown: bool = True
    enforce_code: bool = False  # Off by default (too aggressive)
    enforce_xml: bool = False

    # Repair attempts
    max_repair_attempts: int = 3
    fallback_to_lossless: bool = True  # If repair fails, use lossless compression


class SyntaxCompressor:
    """Grammar-constrained compression wrapper.

    Wraps other compressors and ensures their output is always valid
    according to the detected grammar.
    """

    def __init__(self, config: SyntaxCompressorConfig | None = None):
        self.config = config or SyntaxCompressorConfig()

    def compress(
        self,
        content: str,
        compressor: callable | None = None,
        grammar_type: SyntaxType | None = None,
    ) -> tuple[str, SyntaxType, bool]:
        """Compress content with grammar validation.

        Args:
            content: Content to compress.
            compressor: Optional compression function(content) -> content.
            grammar_type: Optional grammar type override.

        Returns:
            (compressed_content, detected_grammar, was_valid).
        """
        if not self.config.enabled:
            return content, SyntaxType.FREEFORM, True

        # Detect grammar
        detected = detect_syntax(content)

        # Check if this grammar type is enforced
        if not self._is_enforced(detected):
            if compressor:
                return compressor(content), detected, True
            return content, detected, True

        # Apply compression
        if compressor:
            compressed = compressor(content)
        else:
            compressed = content

        # Validate and repair
        is_valid, repaired, _ = validate_and_repair(compressed, detected)

        if is_valid:
            return repaired, detected, True

        # Repair failed — fall back to lossless if configured
        if self.config.fallback_to_lossless:
            # Return original content (lossless)
            return content, detected, False

        return repaired, detected, False

    def _is_enforced(self, grammar_type: SyntaxType) -> bool:
        """Check if a grammar type is enforced."""
        if grammar_type == SyntaxType.JSON:
            return self.config.enforce_json
        if grammar_type == SyntaxType.MARKDOWN:
            return self.config.enforce_markdown
        if grammar_type == SyntaxType.CODE:
            return self.config.enforce_code
        if grammar_type == SyntaxType.XML:
            return self.config.enforce_xml
        return False
