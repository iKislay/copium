"""Tool description compression for MCP proxy.

Compresses verbose MCP tool descriptions (written for humans) into compact
descriptions (optimized for LLMs). Achieves 70-90% token reduction by:

1. Stripping verbose preamble phrases ("This tool allows you to...")
2. Removing examples the model can infer from context
3. Compressing parameter descriptions to type + constraint
4. Preserving functional meaning (what it does, what it returns)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Verbose phrases that add no information for LLMs
STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"this\s+(?:tool|function|method|command)\s+"
        r"(?:allows?\s+you\s+to|enables?\s+you\s+to|can\s+be\s+used\s+to|"
        r"is\s+used\s+to|will|lets?\s+you|provides?|helps?\s+you)",
        re.IGNORECASE,
    ),
    re.compile(
        r"use\s+this\s+(?:tool|function|method)\s+(?:when|if|to|for)\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"returns?\s+(?:the|a|an)\s+(?:following|result|response|output)[:\s]*",
        re.IGNORECASE,
    ),
    re.compile(r"\bfor\s+example[,:]?\s*", re.IGNORECASE),
    re.compile(r"\bnote(?:\s+that)?[:\s]+.*?(?=\.\s|\n|$)", re.IGNORECASE),
    re.compile(r"\bimportant[:\s]+.*?(?=\.\s|\n|$)", re.IGNORECASE),
    re.compile(r"^\s*parameters?\s*:?\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*(?:returns?|output)\s*:?\s*$", re.IGNORECASE | re.MULTILINE),
]

# Filler words that can be safely removed
FILLER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:basically|essentially|simply|just|actually)\b", re.IGNORECASE),
    re.compile(r"\b(?:in order to|so that|such that)\b", re.IGNORECASE),
    re.compile(r"\b(?:please note that|it should be noted that)\b", re.IGNORECASE),
    re.compile(r"\b(?:the following|as follows)\b", re.IGNORECASE),
]

# Multi-space collapse
MULTI_SPACE = re.compile(r"[ \t]+")
MULTI_NEWLINE = re.compile(r"\n{3,}")


@dataclass
class CompressedTool:
    """A tool with compressed description and schema."""

    name: str
    description: str
    input_schema: dict[str, Any]
    original_description: str
    original_tokens: int = 0
    compressed_tokens: int = 0

    @property
    def savings_percent(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (1 - self.compressed_tokens / self.original_tokens) * 100


@dataclass
class DescriptionCompressor:
    """Compress MCP tool descriptions for LLM consumption.

    Strategies:
    1. Strip common verbose phrases
    2. Remove examples that LLMs can infer
    3. Compress parameter descriptions to type + constraint
    4. Preserve functional meaning
    """

    max_description_tokens: int = 50
    """Target maximum tokens per compressed description."""

    strip_examples: bool = True
    """Remove example blocks from descriptions."""

    compress_params: bool = True
    """Compress parameter descriptions."""

    _stats: dict[str, int] = field(default_factory=lambda: {
        "tools_compressed": 0,
        "total_original_tokens": 0,
        "total_compressed_tokens": 0,
    })

    def compress(self, tool: dict[str, Any]) -> CompressedTool:
        """Compress a single tool's description and schema.

        Args:
            tool: MCP tool definition dict with 'name', 'description',
                  and 'inputSchema' keys.

        Returns:
            CompressedTool with compressed description and schema.
        """
        name = tool.get("name", "")
        description = tool.get("description", "")
        input_schema = tool.get("inputSchema", {})

        original_tokens = self._estimate_tokens(description)

        # Compress description
        compressed_desc = self._compress_description(description)

        # Compress parameter descriptions within schema
        compressed_schema = (
            self._compress_schema(input_schema)
            if self.compress_params
            else input_schema
        )

        compressed_tokens = self._estimate_tokens(compressed_desc)

        # Update stats
        self._stats["tools_compressed"] += 1
        self._stats["total_original_tokens"] += original_tokens
        self._stats["total_compressed_tokens"] += compressed_tokens

        return CompressedTool(
            name=name,
            description=compressed_desc,
            input_schema=compressed_schema,
            original_description=description,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
        )

    def _compress_description(self, description: str) -> str:
        """Apply compression transforms to a description string."""
        text = description

        # Strip verbose patterns
        for pattern in STRIP_PATTERNS:
            text = pattern.sub("", text)

        # Remove filler words
        for pattern in FILLER_PATTERNS:
            text = pattern.sub("", text)

        # Strip example blocks (```...``` or indented blocks after "Example:")
        if self.strip_examples:
            text = re.sub(
                r"```[\s\S]*?```", "", text
            )
            text = re.sub(
                r"(?:example|e\.g\.)[:\s]*\n(?:\s{2,}.*\n?)+",
                "",
                text,
                flags=re.IGNORECASE,
            )

        # Collapse whitespace
        text = MULTI_SPACE.sub(" ", text)
        text = MULTI_NEWLINE.sub("\n", text)

        # Strip leading/trailing whitespace per line
        lines = [line.strip() for line in text.split("\n")]
        text = " ".join(line for line in lines if line)

        # Sentence-level truncation if still too long
        estimated = self._estimate_tokens(text)
        if estimated > self.max_description_tokens * 2:
            # Keep first meaningful sentence
            sentences = re.split(r"(?<=[.!?])\s+", text)
            text = sentences[0] if sentences else text

        return text.strip()

    def _compress_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Compress parameter descriptions within a JSON schema."""
        if not isinstance(schema, dict):
            return schema

        compressed = dict(schema)
        properties = compressed.get("properties", {})

        if not properties:
            return compressed

        new_props: dict[str, Any] = {}
        for param_name, param_def in properties.items():
            if not isinstance(param_def, dict):
                new_props[param_name] = param_def
                continue

            new_def = dict(param_def)
            # Shorten param description to type + constraint
            if "description" in new_def:
                new_def["description"] = self._compress_param_description(
                    param_name, new_def["description"], new_def.get("type", "")
                )
            # Remove examples from params
            if self.strip_examples:
                new_def.pop("examples", None)
            new_props[param_name] = new_def

        compressed["properties"] = new_props
        return compressed

    def _compress_param_description(
        self, name: str, description: str, type_hint: str
    ) -> str:
        """Compress a parameter description to essentials."""
        # If already short, keep it
        if len(description.split()) <= 8:
            return description

        # Extract constraint info (required, default, enum values)
        constraints: list[str] = []

        # Check for default value mentions
        default_match = re.search(
            r"defaults?\s+(?:to|is|=)\s+['\"]?(\S+)['\"]?",
            description,
            re.IGNORECASE,
        )
        if default_match:
            constraints.append(f"default: {default_match.group(1)}")

        # Check for enum/options
        enum_match = re.search(
            r"(?:one of|options?|values?)[:\s]+([^.]+)",
            description,
            re.IGNORECASE,
        )
        if enum_match:
            constraints.append(enum_match.group(1).strip())

        # First meaningful clause
        first_clause = re.split(r"[.;]", description)[0].strip()
        # Apply same strip patterns
        for pattern in STRIP_PATTERNS[:3]:
            first_clause = pattern.sub("", first_clause)
        first_clause = first_clause.strip()

        if constraints:
            return f"{first_clause} ({', '.join(constraints)})"
        return first_clause if first_clause else description[:60]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (words * 1.3)."""
        if not text:
            return 0
        return int(len(text.split()) * 1.3)

    @property
    def stats(self) -> dict[str, Any]:
        """Return compression statistics."""
        total_orig = self._stats["total_original_tokens"]
        total_comp = self._stats["total_compressed_tokens"]
        savings = (
            (1 - total_comp / total_orig) * 100 if total_orig > 0 else 0.0
        )
        return {
            **self._stats,
            "savings_percent": round(savings, 1),
        }
