"""Serialization utilities for SharedContext entries.

Handles compression and decompression of stored context content,
and conversion between in-memory and persistent representations.
"""

from __future__ import annotations

import json
import logging
import zlib
from typing import Any

logger = logging.getLogger(__name__)

# Compression level for stored content (1=fast, 9=best compression)
_COMPRESS_LEVEL = 6


def compress_content(content: str) -> bytes:
    """Compress a string for storage.

    Uses zlib compression to reduce storage footprint of original content.
    The LLM-compressed version is stored as-is (already small).
    """
    return zlib.compress(content.encode("utf-8"), level=_COMPRESS_LEVEL)


def decompress_content(data: bytes) -> str:
    """Decompress stored content back to string."""
    return zlib.decompress(data).decode("utf-8")


def serialize_metadata(metadata: dict[str, Any]) -> str:
    """Serialize metadata dict to JSON string for storage."""
    return json.dumps(metadata, separators=(",", ":"), default=str)


def deserialize_metadata(data: str) -> dict[str, Any]:
    """Deserialize JSON string back to metadata dict."""
    if not data:
        return {}
    return json.loads(data)


def serialize_tags(tags: list[str]) -> str:
    """Serialize tags list to JSON string."""
    return json.dumps(tags)


def deserialize_tags(data: str) -> list[str]:
    """Deserialize JSON string back to tags list."""
    if not data:
        return []
    return json.loads(data)


def serialize_transforms(transforms: list[str]) -> str:
    """Serialize transforms list to JSON string."""
    return json.dumps(transforms)


def deserialize_transforms(data: str) -> list[str]:
    """Deserialize JSON string back to transforms list."""
    if not data:
        return []
    return json.loads(data)


def estimate_token_count(text: str) -> int:
    """Rough token estimate (4 chars per token heuristic).

    For actual token counting, use the tokenizer module.
    This is a fast fallback when exact counts aren't needed.
    """
    return max(1, len(text) // 4)
