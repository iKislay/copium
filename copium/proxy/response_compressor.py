"""MCP tool call response compressor.

Compresses tool call responses (outputs) before returning them to the agent.
This is the other half of the ContextCrumb-beating strategy - not just
compressing tool descriptions (input), but also compressing tool outputs.

ContextCrumb's `contextcrumb-shrink` only compresses tool schemas.
Copium compresses both schemas AND responses, with CCR reversibility.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CompressedResponse:
    """A compressed tool call response."""

    tool_name: str
    original: str
    compressed: str
    original_tokens: int = 0
    compressed_tokens: int = 0
    ccr_key: str = ""
    compression_mode: str = ""

    @property
    def tokens_saved(self) -> int:
        return max(0, self.original_tokens - self.compressed_tokens)

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (self.tokens_saved / self.original_tokens) * 100

    @property
    def is_reversible(self) -> bool:
        return bool(self.ccr_key)


@dataclass
class ResponseCompressionStats:
    """Aggregate stats for response compression."""

    total_responses: int = 0
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0
    cache_hits: int = 0
    largest_saving: int = 0

    @property
    def total_saved(self) -> int:
        return max(0, self.total_original_tokens - self.total_compressed_tokens)

    @property
    def average_savings_pct(self) -> float:
        if self.total_original_tokens == 0:
            return 0.0
        return (self.total_saved / self.total_original_tokens) * 100


class ToolResponseCompressor:
    """Compresses MCP tool call responses for reduced token usage.

    Applies content-type-aware compression to tool outputs:
    - JSON: structural compression, redundancy removal
    - Code: language-aware compression (imports, comments)
    - Text: sentence-level compression
    - Logs: dedup, timestamp removal, grouping
    - Errors: stack frame reduction, message extraction

    All with optional CCR key for reversible decompression.

    Example:
        >>> compressor = ToolResponseCompressor()
        >>> result = compressor.compress("read_file", large_file_content)
        >>> print(f"Saved {result.savings_pct:.0f}% ({result.tokens_saved} tokens)")
        >>> # result.ccr_key allows restoration if needed
    """

    def __init__(
        self,
        *,
        max_output_tokens: int = 2000,
        aggressiveness: float = 0.5,
        enable_ccr: bool = True,
    ):
        """Initialize response compressor.

        Args:
            max_output_tokens: Target max tokens for compressed output.
            aggressiveness: 0.0-1.0 compression aggressiveness.
            enable_ccr: Whether to store originals for CCR retrieval.
        """
        self._max_output_tokens = max_output_tokens
        self._aggressiveness = max(0.0, min(1.0, aggressiveness))
        self._enable_ccr = enable_ccr
        self._ccr_store: dict[str, str] = {}
        self._stats = ResponseCompressionStats()

    def compress(self, tool_name: str, response: str) -> CompressedResponse:
        """Compress a tool call response.

        Args:
            tool_name: Name of the tool that generated this response.
            response: The raw tool output.

        Returns:
            CompressedResponse with compressed content and metadata.
        """
        original_tokens = len(response) // 4

        # If already within budget, skip compression
        if original_tokens <= self._max_output_tokens:
            self._stats.total_responses += 1
            self._stats.total_original_tokens += original_tokens
            self._stats.total_compressed_tokens += original_tokens
            return CompressedResponse(
                tool_name=tool_name,
                original=response,
                compressed=response,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
            )

        # Detect content type and apply appropriate strategy
        content_type = self._detect_content_type(response)
        compressed = self._compress_by_type(response, content_type, tool_name)
        compressed_tokens = len(compressed) // 4

        # Store for CCR if enabled
        ccr_key = ""
        if self._enable_ccr and compressed != response:
            ccr_key = hashlib.sha256(response.encode()).hexdigest()[:16]
            self._ccr_store[ccr_key] = response

        self._stats.total_responses += 1
        self._stats.total_original_tokens += original_tokens
        self._stats.total_compressed_tokens += compressed_tokens
        saving = original_tokens - compressed_tokens
        if saving > self._stats.largest_saving:
            self._stats.largest_saving = saving

        return CompressedResponse(
            tool_name=tool_name,
            original=response,
            compressed=compressed,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            ccr_key=ccr_key,
            compression_mode=content_type,
        )

    def restore(self, ccr_key: str) -> str | None:
        """Restore original response from CCR key.

        Args:
            ccr_key: The CCR key from CompressedResponse.

        Returns:
            Original response or None if not found.
        """
        return self._ccr_store.get(ccr_key)

    @property
    def stats(self) -> ResponseCompressionStats:
        """Get compression statistics."""
        return self._stats

    def _detect_content_type(self, content: str) -> str:
        """Detect the content type of a tool response."""
        stripped = content.strip()

        # JSON detection
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(stripped)
                return "json"
            except (json.JSONDecodeError, ValueError):
                pass

        # Code detection
        code_indicators = [
            r"^\s*(def|class|function|fn|pub|import|from|use|#include)\s",
            r"^\s*(if|for|while|match|switch)\s",
            r"[{};]\s*$",
        ]
        code_line_count = sum(
            1 for line in content.split("\n")[:20]
            if any(re.match(p, line) for p in code_indicators)
        )
        if code_line_count >= 3:
            return "code"

        # Log detection
        log_patterns = [
            r"^\d{4}-\d{2}-\d{2}",
            r"^\[?(INFO|DEBUG|WARN|ERROR|TRACE)\]?",
            r"^\d{2}:\d{2}:\d{2}",
        ]
        log_line_count = sum(
            1 for line in content.split("\n")[:20]
            if any(re.match(p, line) for p in log_patterns)
        )
        if log_line_count >= 3:
            return "log"

        # Error detection
        if any(kw in content for kw in ("Traceback", "Error:", "Exception", "panic")):
            return "error"

        return "text"

    def _compress_by_type(self, content: str, content_type: str, tool_name: str) -> str:
        """Apply type-specific compression."""
        if content_type == "json":
            return self._compress_json(content)
        elif content_type == "code":
            return self._compress_code(content)
        elif content_type == "log":
            return self._compress_log(content)
        elif content_type == "error":
            return self._compress_error(content)
        else:
            return self._compress_text(content)

    def _compress_json(self, content: str) -> str:
        """Compress JSON response."""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return self._compress_text(content)

        # Compact JSON (no indentation)
        compact = json.dumps(data, separators=(",", ":"))

        # If still too large, truncate arrays/deep objects
        if len(compact) // 4 > self._max_output_tokens:
            data = self._truncate_json(data, depth=0)
            compact = json.dumps(data, separators=(",", ":"))

        return compact

    def _compress_code(self, content: str) -> str:
        """Compress code response (remove comments, compress bodies)."""
        lines = content.split("\n")
        result: list[str] = []
        total_tokens = 0

        for line in lines:
            stripped = line.strip()

            # Skip pure comment lines at high aggressiveness
            if self._aggressiveness > 0.5:
                if stripped.startswith("#") and not stripped.startswith("#!"):
                    continue
                if stripped.startswith("//"):
                    continue

            # Skip blank lines in sequence
            if not stripped and result and not result[-1].strip():
                continue

            tokens = len(line) // 4 + 1
            if total_tokens + tokens > self._max_output_tokens:
                remaining = len(lines) - len(result)
                result.append(f"... ({remaining} more lines)")
                break

            result.append(line)
            total_tokens += tokens

        return "\n".join(result)

    def _compress_log(self, content: str) -> str:
        """Compress log output (dedup, group, remove timestamps)."""
        lines = content.split("\n")
        result: list[str] = []
        seen_patterns: dict[str, int] = {}

        for line in lines:
            # Remove/shorten timestamps
            compressed_line = re.sub(
                r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*Z?\s*",
                "",
                line,
            )

            # Deduplicate similar lines
            pattern = re.sub(r"\b\d+\b", "N", compressed_line)
            pattern = re.sub(r"\b[0-9a-f]{8,}\b", "HASH", pattern)

            if pattern in seen_patterns:
                seen_patterns[pattern] += 1
                continue

            seen_patterns[pattern] = 1
            result.append(compressed_line)

            if len("\n".join(result)) // 4 > self._max_output_tokens:
                break

        # Append dedup counts
        repeated = [(p, c) for p, c in seen_patterns.items() if c > 1]
        if repeated:
            result.append(f"({len(repeated)} patterns repeated, {sum(c for _, c in repeated)} total)")

        return "\n".join(result)

    def _compress_error(self, content: str) -> str:
        """Compress error/traceback output."""
        lines = content.split("\n")
        result: list[str] = []
        in_traceback = False
        frame_count = 0
        max_frames = 3

        for line in lines:
            if "Traceback" in line:
                in_traceback = True
                result.append(line)
                continue

            if in_traceback:
                if line.startswith("  File"):
                    frame_count += 1
                    if frame_count <= max_frames:
                        result.append(line)
                    continue
                elif line.strip() and not line.startswith(" "):
                    # Error message line
                    if frame_count > max_frames:
                        result.append(f"  ... ({frame_count - max_frames} more frames)")
                    result.append(line)
                    in_traceback = False
                    frame_count = 0
                    continue
                elif frame_count <= max_frames:
                    result.append(line)
            else:
                result.append(line)

        return "\n".join(result)

    def _compress_text(self, content: str) -> str:
        """Compress plain text response."""
        lines = content.split("\n")
        result: list[str] = []
        total_tokens = 0

        for line in lines:
            # Skip empty lines in sequence
            if not line.strip() and result and not result[-1].strip():
                continue

            tokens = len(line) // 4 + 1
            if total_tokens + tokens > self._max_output_tokens:
                remaining = len(lines) - len(result)
                result.append(f"... ({remaining} more lines omitted)")
                break

            result.append(line)
            total_tokens += tokens

        return "\n".join(result)

    def _truncate_json(self, data: Any, depth: int) -> Any:
        """Truncate deep/large JSON structures."""
        max_depth = 4
        max_array_items = 5

        if depth > max_depth:
            if isinstance(data, dict):
                return {"...": f"{len(data)} keys"}
            if isinstance(data, list):
                return [f"... ({len(data)} items)"]
            return data

        if isinstance(data, dict):
            result = {}
            for i, (k, v) in enumerate(data.items()):
                if i >= 10:  # Max 10 keys at each level
                    result["..."] = f"{len(data) - 10} more keys"
                    break
                result[k] = self._truncate_json(v, depth + 1)
            return result

        if isinstance(data, list):
            if len(data) <= max_array_items:
                return [self._truncate_json(item, depth + 1) for item in data]
            truncated = [self._truncate_json(item, depth + 1) for item in data[:max_array_items]]
            truncated.append(f"... ({len(data) - max_array_items} more items)")
            return truncated

        return data
