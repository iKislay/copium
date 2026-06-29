"""Tool response compression for MCP proxy.

Compresses MCP tool call responses using Copium's existing transform
pipeline (ContentRouter). Achieves 60-95% reduction depending on
content type. Stores originals in CCR for on-demand retrieval.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompressedResponse:
    """A compressed tool response with metadata."""

    content: str
    """The compressed response content."""

    original_hash: str
    """Hash of the original response (for CCR retrieval)."""

    original_tokens: int
    """Estimated tokens of the original response."""

    compressed_tokens: int
    """Estimated tokens of the compressed response."""

    tool_name: str
    """Name of the tool that produced this response."""

    timestamp: float = field(default_factory=time.time)
    """When the compression was performed."""

    @property
    def savings_percent(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (1 - self.compressed_tokens / self.original_tokens) * 100


@dataclass
class ResponseCompressor:
    """Compress tool responses using content-type-aware strategies.

    Uses Copium's existing compression infrastructure when available,
    falling back to basic truncation-with-summary for large outputs.
    """

    min_tokens_to_compress: int = 100
    """Minimum response size before compression is applied."""

    max_output_tokens: int = 500
    """Target maximum output tokens for compressed responses."""

    ccr_enabled: bool = True
    """Whether to store originals for retrieval."""

    _store: dict[str, str] = field(default_factory=dict)
    """In-memory CCR store: hash -> original content."""

    _stats: dict[str, int] = field(default_factory=lambda: {
        "responses_compressed": 0,
        "responses_passed_through": 0,
        "total_original_tokens": 0,
        "total_compressed_tokens": 0,
    })

    def compress(self, tool_name: str, response: str) -> CompressedResponse:
        """Compress a tool response.

        Args:
            tool_name: Name of the tool that generated the response.
            response: The raw tool response string.

        Returns:
            CompressedResponse with compressed content and metadata.
        """
        original_tokens = self._estimate_tokens(response)

        # Skip compression for small responses
        if original_tokens < self.min_tokens_to_compress:
            self._stats["responses_passed_through"] += 1
            return CompressedResponse(
                content=response,
                original_hash="",
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                tool_name=tool_name,
            )

        # Generate hash for CCR retrieval
        content_hash = self._hash_content(response)

        # Store original if CCR is enabled
        if self.ccr_enabled:
            self._store[content_hash] = response

        # Try to use Copium's ContentRouter if available
        compressed = self._compress_content(tool_name, response)
        compressed_tokens = self._estimate_tokens(compressed)

        # Add retrieval note
        if self.ccr_enabled and compressed != response:
            compressed += (
                f"\n\n[Compressed {original_tokens}→{compressed_tokens} tokens. "
                f"Full: copium_retrieve(hash='{content_hash[:12]}')]"
            )
            compressed_tokens = self._estimate_tokens(compressed)

        self._stats["responses_compressed"] += 1
        self._stats["total_original_tokens"] += original_tokens
        self._stats["total_compressed_tokens"] += compressed_tokens

        return CompressedResponse(
            content=compressed,
            original_hash=content_hash,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            tool_name=tool_name,
        )

    def retrieve(self, hash_prefix: str) -> str | None:
        """Retrieve original content by hash prefix.

        Args:
            hash_prefix: Full or partial hash of the original content.

        Returns:
            Original content string or None if not found.
        """
        # Exact match first
        if hash_prefix in self._store:
            return self._store[hash_prefix]

        # Prefix match
        for key, value in self._store.items():
            if key.startswith(hash_prefix):
                return value
        return None

    def _compress_content(self, tool_name: str, content: str) -> str:
        """Apply content-aware compression strategies."""
        # Try using Copium's universal compressor
        try:
            from copium.compression import compress as copium_compress

            result = copium_compress(content)
            if hasattr(result, "compressed") and result.compressed:
                return result.compressed
        except (ImportError, Exception):
            pass

        # Fallback: smart truncation
        return self._smart_truncate(tool_name, content)

    def _smart_truncate(self, tool_name: str, content: str) -> str:
        """Intelligently truncate long responses."""
        lines = content.split("\n")
        total_lines = len(lines)

        if total_lines <= 20:
            return content

        # Keep first and last sections (bookend strategy)
        head_count = min(10, total_lines // 3)
        tail_count = min(5, total_lines // 4)

        head = lines[:head_count]
        tail = lines[-tail_count:] if tail_count > 0 else []
        omitted = total_lines - head_count - tail_count

        parts = head + [f"\n... ({omitted} lines omitted) ...\n"] + tail
        return "\n".join(parts)

    @staticmethod
    def _hash_content(content: str) -> str:
        """Generate a short hash for content addressing."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate."""
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
            "store_size": len(self._store),
            "savings_percent": round(savings, 1),
        }
