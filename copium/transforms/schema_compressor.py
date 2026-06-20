"""Schema Compression — aggressive compression for OpenAI Function Calling tool definitions.

Tool schemas get resent identically every turn. This module compresses them
aggressively: truncates descriptions, removes verbose annotations, simplifies
nested schemas, and strips markdown. ~57% reduction on schemas.

Works on the request body (tools array), not on messages.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SchemaCompressionConfig:
    """Configuration for schema compression."""

    enabled: bool = True

    # Maximum description length (chars). Longer descriptions are truncated
    # to the first sentence.
    max_description_length: int = 120

    # Drop these JSON Schema annotation keys entirely
    drop_keys: frozenset[str] = frozenset(
        {
            "$id",
            "$schema",
            "$comment",
            "deprecated",
            "examples",
            "example",
            "markdownDescription",
            "readOnly",
            "writeOnly",
            "default",  # Drop defaults (model doesn't need them for invocation)
            "format",  # Drop format hints (model can infer from context)
            "pattern",  # Drop regex patterns (too verbose, model ignores them)
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
            "uniqueItems",
            "contentMediaType",
            "contentEncoding",
        }
    )

    # Keys that contain verbose descriptions to truncate
    description_keys: frozenset[str] = frozenset({"description"})

    # Remove markdown formatting from descriptions
    strip_markdown: bool = True

    # Collapse single-value enums to const
    collapse_enums: bool = True

    # Remove empty required arrays
    remove_empty_required: bool = True

    # Strip "type" when it's redundant (e.g., "string" for simple properties)
    strip_redundant_type: bool = False  # Conservative: keep type for safety


def _truncate_description(text: str, max_length: int) -> str:
    """Truncate a description to the first sentence or max_length chars."""
    text = text.strip()
    if len(text) <= max_length:
        return text

    # Try to cut at sentence boundary
    sentence_end = re.search(r"[.!?]\s", text[:max_length + 20])
    if sentence_end and sentence_end.start() <= max_length:
        return text[: sentence_end.start() + 1].strip()

    # Fall back to max_length with ellipsis
    return text[:max_length].rstrip() + "..."


def _strip_markdown(text: str) -> str:
    """Remove common markdown formatting from descriptions."""
    # Remove bold/italic markers
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    # Remove inline code backticks
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove links, keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove heading markers
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    # Collapse whitespace
    text = " ".join(text.split())
    return text


def _compress_schema_node(
    node: Any,
    config: SchemaCompressionConfig,
    parent_key: str | None = None,
) -> Any:
    """Recursively compress a JSON Schema node."""
    if isinstance(node, list):
        return [_compress_schema_node(item, config, parent_key) for item in node]

    if not isinstance(node, dict):
        return node

    result: dict[str, Any] = {}
    for key, value in node.items():
        # Drop annotation keys
        if key in config.drop_keys:
            continue

        # Truncate descriptions
        if key in config.description_keys and isinstance(value, str):
            if config.strip_markdown:
                value = _strip_markdown(value)
            value = _truncate_description(value, config.max_description_length)
            result[key] = value
            continue

        # Collapse single-value enums to const
        if config.collapse_enums and key == "enum" and isinstance(value, list):
            if len(value) == 1:
                result["const"] = value[0]
                continue

        # Remove empty required arrays
        if config.remove_empty_required and key == "required" and value == []:
            continue

        # Recurse into nested schemas
        result[key] = _compress_schema_node(value, config, key)

    return result


def compress_tool_schemas(
    tools: list[dict[str, Any]],
    config: SchemaCompressionConfig | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Compress OpenAI function calling tool definitions.

    Args:
        tools: List of tool definitions (OpenAI format).
        config: Compression configuration.

    Returns:
        (compressed_tools, bytes_before, bytes_after)
    """
    config = config or SchemaCompressionConfig()
    if not config.enabled or not tools:
        return tools, 0, 0

    before_json = json.dumps(tools, separators=(",", ":"))
    before_bytes = len(before_json.encode("utf-8"))

    compressed = copy.deepcopy(tools)
    for tool in compressed:
        # Handle OpenAI format: {"type": "function", "function": {...}}
        if "function" in tool and isinstance(tool["function"], dict):
            func = tool["function"]
            if "parameters" in func and isinstance(func["parameters"], dict):
                func["parameters"] = _compress_schema_node(
                    func["parameters"], config, "parameters"
                )
            # Truncate function description
            if "description" in func and isinstance(func["description"], str):
                if config.strip_markdown:
                    func["description"] = _strip_markdown(func["description"])
                func["description"] = _truncate_description(
                    func["description"], config.max_description_length
                )

        # Handle Anthropic format: {"name": ..., "description": ..., "input_schema": {...}}
        if "input_schema" in tool and isinstance(tool["input_schema"], dict):
            tool["input_schema"] = _compress_schema_node(
                tool["input_schema"], config, "input_schema"
            )
            if "description" in tool and isinstance(tool["description"], str):
                if config.strip_markdown:
                    tool["description"] = _strip_markdown(tool["description"])
                tool["description"] = _truncate_description(
                    tool["description"], config.max_description_length
                )

    after_json = json.dumps(compressed, separators=(",", ":"))
    after_bytes = len(after_json.encode("utf-8"))

    return compressed, before_bytes, after_bytes


def compress_tools_in_body(
    body: dict[str, Any],
    config: SchemaCompressionConfig | None = None,
) -> tuple[dict[str, Any], bool, int, int]:
    """Compress tool schemas in an OpenAI-compatible request body.

    Modifies the 'tools' key in place (after deep copy).

    Args:
        body: Request body dict.
        config: Compression configuration.

    Returns:
        (modified_body, was_modified, bytes_before, bytes_after)
    """
    config = config or SchemaCompressionConfig()
    tools = body.get("tools")
    if not isinstance(tools, list) or not tools:
        return body, False, 0, 0

    compressed, before, after = compress_tool_schemas(tools, config)
    if after >= before:
        return body, False, before, after

    modified = copy.deepcopy(body)
    modified["tools"] = compressed
    return modified, True, before, after
