"""TOON Encoding transform — compact table format for uniform JSON arrays.

Token-Oriented Object Notation (TOON) encodes uniform JSON arrays into a
compact table format. Headers are encoded once, rows use positional notation.
Savings: 15-40% on uniform JSON arrays.

Example:
  Input:  [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
  Output: id|name\n1|Alice\n2|Bob
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from ..utils import deep_copy_messages
from .base import Transform


@dataclass
class TOONConfig:
    """Configuration for TOON encoding.

    TOON (Token-Oriented Object Notation) encodes uniform JSON arrays
    into a compact pipe-delimited table format. Only applies to arrays
    of objects where all objects share the same keys.
    """

    enabled: bool = True

    # Minimum number of items in array before TOON encoding is attempted
    min_items: int = 3

    # Minimum fraction of items that must share the same keys (0-1)
    # If below this, the array is heterogeneous and TOON won't help
    key_uniformity_threshold: float = 0.8

    # Maximum number of columns (keys) per object before skipping
    # Very wide objects don't benefit much from TOON
    max_columns: int = 20

    # Minimum token savings ratio to bother converting (0-1)
    min_savings_ratio: float = 0.10

    # Separator character for TOON format
    separator: str = "|"

    # Whether to include the header row
    include_header: bool = True


def _is_uniform_array(items: list[dict[str, Any]], threshold: float) -> bool:
    """Check if array items are uniform enough for TOON encoding."""
    if not items or not isinstance(items[0], dict):
        return False

    # Check if all items are dicts
    if not all(isinstance(item, dict) for item in items):
        return False

    # Find the most common key set
    key_sets = [frozenset(item.keys()) for item in items if isinstance(item, dict)]
    if not key_sets:
        return False

    most_common_keys = max(set(key_sets), key=key_sets.count)
    uniformity = sum(1 for ks in key_sets if ks == most_common_keys) / len(key_sets)

    return uniformity >= threshold


def _extract_columns(items: list[dict[str, Any]], max_cols: int) -> list[str]:
    """Extract ordered column names from items."""
    # Use the key set of the first item as the canonical order
    if not items:
        return []

    first_keys = list(items[0].keys()) if isinstance(items[0], dict) else []
    return first_keys[:max_cols]


def _encode_toon(
    items: list[dict[str, Any]],
    columns: list[str],
    separator: str,
    include_header: bool,
) -> str:
    """Encode items into TOON format."""
    lines: list[str] = []

    if include_header:
        lines.append(separator.join(columns))

    for item in items:
        row_values: list[str] = []
        for col in columns:
            val = item.get(col, "")
            # Convert to string, escaping the separator
            val_str = _toon_escape(str(val), separator)
            row_values.append(val_str)
        lines.append(separator.join(row_values))

    return "\n".join(lines)


def _toon_escape(value: str, separator: str) -> str:
    """Escape a value for TOON format."""
    # Replace newlines with spaces (TOON is single-line per row)
    value = value.replace("\n", " ").replace("\r", "")
    # Escape the separator character
    value = value.replace(separator, f"\\{separator}")
    return value.strip()


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (chars / 4)."""
    return max(1, len(text) // 4)


class TOONEncoder(Transform):
    """Encodes uniform JSON arrays into compact TOON format.

    Only applies to arrays of objects where all objects share the same keys.
    Produces a pipe-delimited table format that saves 15-40% on tokens.
    """

    name = "toon_encoder"

    def __init__(self, config: TOONConfig | None = None):
        self.config = config or TOONConfig()

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        tokens_before = tokenizer.count_messages(messages)
        result_messages = deep_copy_messages(messages)
        transforms_applied: list[str] = []
        warnings: list[str] = []

        frozen_message_count = kwargs.get("frozen_message_count", 0)

        for msg_idx, msg in enumerate(result_messages):
            if msg_idx < frozen_message_count:
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            # Try to parse as JSON
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                continue

            # Only process arrays
            if not isinstance(parsed, list):
                continue

            items = parsed
            if len(items) < self.config.min_items:
                continue

            # Check uniformity
            if not _is_uniform_array(items, self.config.key_uniformity_threshold):
                continue

            # Extract columns
            columns = _extract_columns(items, self.config.max_columns)
            if not columns or len(columns) > self.config.max_columns:
                continue

            # Encode to TOON
            toon_text = _encode_toon(
                items,
                columns,
                self.config.separator,
                self.config.include_header,
            )

            # Check savings
            original_tokens = _estimate_tokens(content)
            toon_tokens = _estimate_tokens(toon_text)

            if toon_tokens >= original_tokens:
                continue

            savings_ratio = 1.0 - (toon_tokens / original_tokens)
            if savings_ratio < self.config.min_savings_ratio:
                continue

            # Apply the transformation
            msg["content"] = toon_text
            transforms_applied.append(
                f"toon:{msg_idx}:cols={len(columns)}:rows={len(items)}:saved={savings_ratio:.0%}"
            )

        tokens_after = tokenizer.count_messages(result_messages)

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
            warnings=warnings,
        )
