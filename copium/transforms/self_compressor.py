"""LLM self-compression marker detection and application.

When the model outputs compression markers alongside its response, this
transform detects them and replaces the original tool output with the
compressed version. No extra inference pass needed — it piggybacks on the
model's normal response generation.

The marker format follows the existing CCR pattern:
  [compress:<hash>:<summary_text>]

Detection flow:
  1. Scan assistant messages for self-compression markers
  2. Find the original tool output with matching content hash
  3. Replace original content with the compressed summary
  4. Record in dedup store for future turns

This addresses the community-requested `_context_updates` pattern where
the LLM compresses its own previous tool results mid-session.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from .base import Transform

logger = logging.getLogger(__name__)

# Pattern: [compress:<16-char-hash>:<summary text>]
_COMPRESS_MARKER_RE = re.compile(
    r"\[compress:([a-f0-9]{16}):(.+?)\]",
    re.DOTALL,
)

# Pattern for _context_updates block (alternative community format)
_CONTEXT_UPDATES_RE = re.compile(
    r"<_context_updates>\s*(.+?)\s*</_context_updates>",
    re.DOTALL,
)

# Individual update entry within _context_updates block
_UPDATE_ENTRY_RE = re.compile(
    r"<update\s+ref=[\"']([^\"']+)[\"']>\s*(.+?)\s*</update>",
    re.DOTALL,
)


def _content_hash(text: str) -> str:
    """SHA-256 hash of content, first 16 hex chars."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class SelfCompressorConfig:
    """Configuration for self-compression marker detection."""

    enabled: bool = True
    # Minimum length of tool output to be eligible for self-compression
    min_content_length: int = 200
    # Maximum number of replacements per apply() call
    max_replacements_per_pass: int = 20
    # Whether to strip markers from assistant messages after processing
    strip_markers: bool = True
    # Whether to support _context_updates XML block format
    support_context_updates: bool = True


@dataclass
class SelfCompressionStats:
    """Statistics from a self-compression pass."""

    markers_found: int = 0
    replacements_made: int = 0
    tokens_saved: int = 0
    unmatched_markers: list[str] = field(default_factory=list)


class SelfCompressor(Transform):
    """Detect and apply LLM self-compression markers.

    When the model outputs a [compress:<hash>:<summary>] marker, this
    transform finds the original tool output and replaces it with the
    summary. No extra inference pass needed — it piggybacks on the
    model's normal response.
    """

    name = "self_compressor"

    def __init__(self, config: SelfCompressorConfig | None = None) -> None:
        self.config = config or SelfCompressorConfig()
        # Track content hashes → message index for fast lookup
        self._content_index: dict[str, int] = {}

    def should_apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> bool:
        """Only apply if there are assistant messages that might contain markers."""
        if not self.config.enabled:
            return False
        return any(
            msg.get("role") == "assistant"
            for msg in messages[-10:]  # Only check recent messages
        )

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Scan for self-compression markers and apply replacements."""
        frozen_count = kwargs.get("frozen_message_count", 0)
        tokens_before = tokenizer.count_messages(messages)

        # Build content hash index for tool outputs
        self._build_content_index(messages, frozen_count)

        stats = SelfCompressionStats()

        # Process assistant messages for compression markers
        for i in range(frozen_count, len(messages)):
            msg = messages[i]
            if msg.get("role") != "assistant":
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            # Check for [compress:hash:summary] markers
            self._process_compress_markers(
                messages, content, i, stats, frozen_count
            )

            # Check for _context_updates blocks
            if self.config.support_context_updates:
                self._process_context_updates(
                    messages, content, i, stats, frozen_count
                )

        tokens_after = tokenizer.count_messages(messages)
        transforms_applied = []
        if stats.replacements_made > 0:
            transforms_applied.append(
                f"self_compressor:{stats.replacements_made}_replacements"
            )
            logger.info(
                "SelfCompressor: %d markers found, %d replacements made, "
                "%d tokens saved",
                stats.markers_found,
                stats.replacements_made,
                tokens_before - tokens_after,
            )

        return TransformResult(
            messages=messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
            markers_inserted=[],
        )

    def _build_content_index(
        self, messages: list[dict[str, Any]], frozen_count: int
    ) -> None:
        """Index tool output content hashes for fast lookup."""
        self._content_index.clear()
        for i, msg in enumerate(messages):
            if i < frozen_count:
                continue
            role = msg.get("role", "")
            if role not in ("tool", "function", "tool_result"):
                continue
            content = self._extract_text_content(msg)
            if len(content) >= self.config.min_content_length:
                h = _content_hash(content)
                self._content_index[h] = i

    def _extract_text_content(self, msg: dict[str, Any]) -> str:
        """Extract text content from a message (handles string and list formats)."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)
        return ""

    def _process_compress_markers(
        self,
        messages: list[dict[str, Any]],
        content: str,
        msg_idx: int,
        stats: SelfCompressionStats,
        frozen_count: int,
    ) -> None:
        """Process [compress:hash:summary] markers in assistant content."""
        markers = _COMPRESS_MARKER_RE.findall(content)
        if not markers:
            return

        stats.markers_found += len(markers)

        for hash_val, summary in markers:
            if stats.replacements_made >= self.config.max_replacements_per_pass:
                break

            target_idx = self._content_index.get(hash_val)
            if target_idx is None:
                stats.unmatched_markers.append(hash_val)
                continue

            # Replace the original tool output with the compressed summary
            target_msg = messages[target_idx]
            replacement = (
                f"[Compressed by model — original {len(self._extract_text_content(target_msg))} chars]\n"
                f"{summary.strip()}"
            )
            self._set_content(target_msg, replacement)
            stats.replacements_made += 1

        # Strip markers from assistant message if configured
        if self.config.strip_markers and markers:
            cleaned = _COMPRESS_MARKER_RE.sub("", content).strip()
            if cleaned != content:
                messages[msg_idx]["content"] = cleaned

    def _process_context_updates(
        self,
        messages: list[dict[str, Any]],
        content: str,
        msg_idx: int,
        stats: SelfCompressionStats,
        frozen_count: int,
    ) -> None:
        """Process <_context_updates> XML blocks in assistant content."""
        updates_match = _CONTEXT_UPDATES_RE.search(content)
        if not updates_match:
            return

        updates_block = updates_match.group(1)
        entries = _UPDATE_ENTRY_RE.findall(updates_block)
        if not entries:
            return

        stats.markers_found += len(entries)

        for ref, summary in entries:
            if stats.replacements_made >= self.config.max_replacements_per_pass:
                break

            # ref can be a hash or a tool_use_id
            target_idx = self._content_index.get(ref)
            if target_idx is None:
                # Try matching by tool_use_id
                target_idx = self._find_by_tool_use_id(messages, ref, frozen_count)
            if target_idx is None:
                stats.unmatched_markers.append(ref)
                continue

            target_msg = messages[target_idx]
            replacement = (
                f"[Context update — original {len(self._extract_text_content(target_msg))} chars]\n"
                f"{summary.strip()}"
            )
            self._set_content(target_msg, replacement)
            stats.replacements_made += 1

        # Strip the _context_updates block from assistant message
        if self.config.strip_markers:
            cleaned = _CONTEXT_UPDATES_RE.sub("", content).strip()
            if cleaned != content:
                messages[msg_idx]["content"] = cleaned

    def _find_by_tool_use_id(
        self, messages: list[dict[str, Any]], tool_use_id: str, frozen_count: int
    ) -> int | None:
        """Find a tool result message by its tool_use_id."""
        for i in range(frozen_count, len(messages)):
            msg = messages[i]
            if msg.get("role") in ("tool", "tool_result"):
                if msg.get("tool_use_id") == tool_use_id:
                    return i
        return None

    def _set_content(self, msg: dict[str, Any], new_content: str) -> None:
        """Set message content (handles string and list formats)."""
        current = msg.get("content", "")
        if isinstance(current, str):
            msg["content"] = new_content
        elif isinstance(current, list):
            # Replace the first text block
            for block in current:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = new_content
                    return
            # No text block found, append one
            current.append({"type": "text", "text": new_content})
        else:
            msg["content"] = new_content
