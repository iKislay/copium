"""Streaming compression for VRAM-constrained environments.

Compresses context in chunks without loading the entire payload
into memory. Processes data as a stream to keep memory footprint
minimal — critical when GPU VRAM is shared with the model.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default chunk size in characters (not tokens)
_DEFAULT_CHUNK_SIZE = 4096


@dataclass
class StreamChunk:
    """A processed chunk of compressed content."""

    content: str
    original_size: int = 0
    compressed_size: int = 0
    is_critical: bool = False  # Critical sections preserved verbatim


@dataclass
class StreamingStats:
    """Statistics from a streaming compression run."""

    chunks_processed: int = 0
    total_original_chars: int = 0
    total_compressed_chars: int = 0
    critical_chunks: int = 0

    @property
    def compression_ratio(self) -> float:
        """Overall compression ratio (0.0-1.0, lower is better)."""
        if self.total_original_chars == 0:
            return 1.0
        return self.total_compressed_chars / self.total_original_chars

    @property
    def savings_pct(self) -> float:
        """Percentage of characters saved."""
        return (1.0 - self.compression_ratio) * 100


class StreamingCompressor:
    """Compress context in a streaming fashion without buffering all content.

    Designed for VRAM-constrained environments where loading the entire
    context into memory for compression would compete with the model
    for GPU memory.

    Usage:
        compressor = StreamingCompressor(chunk_size=4096)

        # Synchronous streaming
        for chunk in compressor.compress_iter(content):
            process(chunk)

        # Async streaming
        async for chunk in compressor.compress_async(content_stream):
            await process(chunk)
    """

    def __init__(
        self,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        preserve_boundaries: bool = True,
    ):
        self.chunk_size = chunk_size
        self.preserve_boundaries = preserve_boundaries
        self._stats = StreamingStats()

    @property
    def stats(self) -> StreamingStats:
        """Get stats from the last compression run."""
        return self._stats

    def compress_iter(self, content: str) -> Iterator[StreamChunk]:
        """Compress content as a synchronous iterator.

        Yields compressed chunks without holding the full content in memory.
        """
        self._stats = StreamingStats()

        # Split on boundaries if requested
        chunks = self._split_content(content)

        for chunk_text in chunks:
            compressed = self._compress_chunk(chunk_text)
            self._stats.chunks_processed += 1
            self._stats.total_original_chars += len(chunk_text)
            self._stats.total_compressed_chars += len(compressed.content)
            if compressed.is_critical:
                self._stats.critical_chunks += 1
            yield compressed

    async def compress_async(
        self, content_stream: AsyncIterator[str]
    ) -> AsyncIterator[StreamChunk]:
        """Compress an async stream of content chunks.

        Buffers input until chunk_size is reached, then compresses
        and yields results.
        """
        self._stats = StreamingStats()
        buffer = ""

        async for incoming in content_stream:
            buffer += incoming
            while len(buffer) >= self.chunk_size:
                chunk_text = buffer[: self.chunk_size]
                buffer = buffer[self.chunk_size :]

                # Find a clean boundary if requested
                if self.preserve_boundaries and buffer:
                    boundary = self._find_boundary(chunk_text)
                    if boundary < len(chunk_text):
                        buffer = chunk_text[boundary:] + buffer
                        chunk_text = chunk_text[:boundary]

                compressed = self._compress_chunk(chunk_text)
                self._stats.chunks_processed += 1
                self._stats.total_original_chars += len(chunk_text)
                self._stats.total_compressed_chars += len(compressed.content)
                if compressed.is_critical:
                    self._stats.critical_chunks += 1
                yield compressed

        # Process remaining buffer
        if buffer:
            compressed = self._compress_chunk(buffer)
            self._stats.chunks_processed += 1
            self._stats.total_original_chars += len(buffer)
            self._stats.total_compressed_chars += len(compressed.content)
            if compressed.is_critical:
                self._stats.critical_chunks += 1
            yield compressed

    def _split_content(self, content: str) -> list[str]:
        """Split content into chunks respecting boundaries."""
        if not self.preserve_boundaries:
            # Simple fixed-size chunks
            return [
                content[i: i + self.chunk_size]
                for i in range(0, len(content), self.chunk_size)
            ]

        chunks = []
        remaining = content
        while remaining:
            if len(remaining) <= self.chunk_size:
                chunks.append(remaining)
                break

            chunk = remaining[: self.chunk_size]
            boundary = self._find_boundary(chunk)
            chunks.append(remaining[:boundary])
            remaining = remaining[boundary:]

        return chunks

    def _find_boundary(self, text: str) -> int:
        """Find the best boundary point in a chunk of text.

        Prefers splitting at (in order):
        1. Double newlines (paragraph breaks)
        2. Single newlines
        3. Sentence ends (. ! ?)
        4. Word boundaries (spaces)
        """
        # Look for double newline in last 25% of chunk
        search_start = len(text) * 3 // 4
        search_region = text[search_start:]

        idx = search_region.rfind("\n\n")
        if idx >= 0:
            return search_start + idx + 2

        idx = search_region.rfind("\n")
        if idx >= 0:
            return search_start + idx + 1

        # Sentence end
        for char in ".!?":
            idx = search_region.rfind(char)
            if idx >= 0:
                return search_start + idx + 1

        # Word boundary
        idx = search_region.rfind(" ")
        if idx >= 0:
            return search_start + idx + 1

        # No good boundary found — split at chunk_size
        return len(text)

    def _compress_chunk(self, text: str) -> StreamChunk:
        """Compress a single chunk of text.

        Uses lightweight heuristic compression:
        - Remove redundant whitespace
        - Collapse repeated blank lines
        - Trim trailing whitespace from lines
        """
        original_size = len(text)

        # Check if this is a critical section (code, JSON, errors)
        if self._is_critical(text):
            return StreamChunk(
                content=text,
                original_size=original_size,
                compressed_size=original_size,
                is_critical=True,
            )

        # Apply lightweight compression
        lines = text.split("\n")
        compressed_lines = []
        prev_blank = False

        for line in lines:
            stripped = line.rstrip()
            is_blank = not stripped

            # Collapse multiple blank lines into one
            if is_blank and prev_blank:
                continue

            compressed_lines.append(stripped)
            prev_blank = is_blank

        compressed = "\n".join(compressed_lines)

        return StreamChunk(
            content=compressed,
            original_size=original_size,
            compressed_size=len(compressed),
            is_critical=False,
        )

    def _is_critical(self, text: str) -> bool:
        """Detect if a chunk contains critical content that shouldn't be compressed."""
        # JSON structures
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return True

        # Code blocks
        if "```" in text:
            return True

        # Error messages
        if any(
            marker in text
            for marker in ("Error:", "Traceback", "FAILED", "panic:", "Exception")
        ):
            return True

        return False
