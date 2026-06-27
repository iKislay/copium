"""Tool description compressor for MCP proxy.

Compresses tool descriptions and parameter schemas while preserving
semantic meaning. Works in conjunction with ProgressiveDisclosure to
minimize token usage for tool definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class CompressedTool:
    """A tool with compressed description and parameters."""

    name: str
    description: str
    parameters: dict[str, Any]
    original_tokens: int = 0
    compressed_tokens: int = 0

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return ((self.original_tokens - self.compressed_tokens) / self.original_tokens) * 100


class ToolDescriptionCompressor:
    """Compresses MCP tool descriptions for reduced token usage.

    Strategies:
    1. Remove redundant phrases ("This tool...", "Use this to...")
    2. Abbreviate common patterns (e.g., "returns" -> "→")
    3. Compress parameter descriptions to essential info
    4. Remove examples from descriptions (keep in full schema only)
    5. Merge similar parameter descriptions
    """

    # Common verbose prefixes to strip
    _VERBOSE_PREFIXES = [
        r"^This tool (?:is used to |allows you to |can be used to |will )",
        r"^Use this (?:tool )?to ",
        r"^A tool (?:that |for |to )",
        r"^The \w+ tool ",
    ]

    # Common abbreviations
    _ABBREVIATIONS = [
        (r"\breturns?\b", "→"),
        (r"\brequired\b", "req"),
        (r"\boptional\b", "opt"),
        (r"\bparameter\b", "param"),
        (r"\bfor example\b", "e.g."),
        (r"\bdefault(?:s to)?\b", "default:"),
    ]

    def __init__(self, aggressiveness: float = 0.5):
        """Initialize compressor.

        Args:
            aggressiveness: 0.0 = minimal compression, 1.0 = maximum compression.
        """
        self._aggressiveness = max(0.0, min(1.0, aggressiveness))
        self._prefix_patterns = [re.compile(p, re.IGNORECASE) for p in self._VERBOSE_PREFIXES]
        self._abbrev_patterns = [(re.compile(p, re.IGNORECASE), r) for p, r in self._ABBREVIATIONS]

    def compress_tool(self, tool: dict[str, Any]) -> CompressedTool:
        """Compress a tool definition.

        Args:
            tool: Tool definition dict with name, description, inputSchema.

        Returns:
            CompressedTool with reduced token usage.
        """
        name = tool.get("name", "")
        description = tool.get("description", "")
        input_schema = tool.get("inputSchema", {})

        original_tokens = self._estimate_tokens(description, input_schema)

        compressed_desc = self._compress_description(description)
        compressed_params = self._compress_parameters(input_schema)

        compressed_tokens = self._estimate_tokens(compressed_desc, compressed_params)

        return CompressedTool(
            name=name,
            description=compressed_desc,
            parameters=compressed_params,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
        )

    def compress_batch(self, tools: list[dict[str, Any]]) -> list[CompressedTool]:
        """Compress multiple tool definitions."""
        return [self.compress_tool(t) for t in tools]

    def _compress_description(self, description: str) -> str:
        """Compress a tool description."""
        if not description:
            return ""

        text = description.strip()

        # Remove verbose prefixes
        for pattern in self._prefix_patterns:
            text = pattern.sub("", text).strip()

        # Capitalize first char after stripping prefix
        if text and text[0].islower():
            text = text[0].upper() + text[1:]

        # Apply abbreviations at higher aggressiveness
        if self._aggressiveness > 0.3:
            for pattern, replacement in self._abbrev_patterns:
                text = pattern.sub(replacement, text)

        # Remove example sections at high aggressiveness
        if self._aggressiveness > 0.6:
            # Remove "Example: ..." or "Examples:\n..." sections
            text = re.sub(r"\n\s*Examples?:.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
            # Remove "e.g., ..." parentheticals
            text = re.sub(r"\s*\(e\.g\..*?\)", "", text)

        # Truncate at high aggressiveness
        if self._aggressiveness > 0.7:
            sentences = text.split(".")
            if len(sentences) > 2:
                text = ".".join(sentences[:2]) + "."

        return text.strip()

    def _compress_parameters(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Compress parameter schema."""
        if not schema:
            return {}

        properties = schema.get("properties", {})
        if not properties:
            return schema

        compressed_props = {}
        for name, prop in properties.items():
            compressed_props[name] = self._compress_property(prop)

        result = dict(schema)
        result["properties"] = compressed_props
        return result

    def _compress_property(self, prop: dict[str, Any]) -> dict[str, Any]:
        """Compress a single parameter property."""
        result = dict(prop)

        # Compress description
        if "description" in result:
            desc = result["description"]
            if self._aggressiveness > 0.5:
                # Keep only first sentence
                first_sentence = desc.split(".")[0].strip()
                if first_sentence:
                    result["description"] = first_sentence
            elif self._aggressiveness > 0.3:
                # Remove examples from description
                result["description"] = re.sub(
                    r"\s*\(e\.g\..*?\)", "", desc
                ).strip()

        # Remove verbose enum descriptions at high aggressiveness
        if self._aggressiveness > 0.7 and "enum" in result:
            result.pop("description", None)  # enum values are self-documenting

        return result

    @staticmethod
    def _estimate_tokens(description: str, schema: dict[str, Any] | str = "") -> int:
        """Estimate token count for description + schema."""
        import json
        if isinstance(schema, dict):
            schema_str = json.dumps(schema)
        else:
            schema_str = schema
        return (len(description) + len(schema_str)) // 4
