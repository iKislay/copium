"""Pre-filter tool outputs based on tool metadata.

Applies type-specific limits BEFORE the output enters the compression
pipeline. Prevents the 500-match grep from ever reaching the model at
full size.

Uses a registry of known tools with their output characteristics to apply
intelligent pre-filtering:
- grep/ripgrep: limit to N lines, prioritize error-related matches
- file reads: limit to N lines, preserve head/tail anchors
- bash commands: limit to N lines, detect output type
- glob/find: limit to N items, alphabetical dedup

This is the first defense layer — downstream transforms (SearchCompressor,
SmartCrusher, etc.) further compress the pre-filtered output.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from .base import Transform

logger = logging.getLogger(__name__)


@dataclass
class ToolProfile:
    """Configuration for a specific tool's pre-filtering behavior."""

    max_lines: int = 200
    max_chars: int = 50_000
    strategy: str = "auto"  # "search", "code", "list", "log", "auto"
    preserve_head: int = 10  # Always keep first N lines
    preserve_tail: int = 5   # Always keep last N lines
    priority_patterns: list[str] = field(default_factory=list)


# Default profiles for common tools
_DEFAULT_PROFILES: dict[str, ToolProfile] = {
    "Grep": ToolProfile(
        max_lines=50, max_chars=30_000, strategy="search",
        preserve_head=5, preserve_tail=3,
        priority_patterns=[r"error", r"Error", r"ERROR", r"failed", r"FAILED"],
    ),
    "grep": ToolProfile(
        max_lines=50, max_chars=30_000, strategy="search",
        preserve_head=5, preserve_tail=3,
        priority_patterns=[r"error", r"Error", r"ERROR", r"failed", r"FAILED"],
    ),
    "ripgrep": ToolProfile(
        max_lines=50, max_chars=30_000, strategy="search",
        preserve_head=5, preserve_tail=3,
        priority_patterns=[r"error", r"Error", r"ERROR", r"failed", r"FAILED"],
    ),
    "Read": ToolProfile(
        max_lines=500, max_chars=80_000, strategy="code",
        preserve_head=30, preserve_tail=10,
    ),
    "read": ToolProfile(
        max_lines=500, max_chars=80_000, strategy="code",
        preserve_head=30, preserve_tail=10,
    ),
    "cat": ToolProfile(
        max_lines=500, max_chars=80_000, strategy="code",
        preserve_head=30, preserve_tail=10,
    ),
    "Bash": ToolProfile(
        max_lines=200, max_chars=50_000, strategy="auto",
        preserve_head=10, preserve_tail=10,
        priority_patterns=[r"error", r"Error", r"warning", r"FAIL"],
    ),
    "bash": ToolProfile(
        max_lines=200, max_chars=50_000, strategy="auto",
        preserve_head=10, preserve_tail=10,
        priority_patterns=[r"error", r"Error", r"warning", r"FAIL"],
    ),
    "Glob": ToolProfile(
        max_lines=50, max_chars=20_000, strategy="list",
        preserve_head=10, preserve_tail=5,
    ),
    "glob": ToolProfile(
        max_lines=50, max_chars=20_000, strategy="list",
        preserve_head=10, preserve_tail=5,
    ),
    "find": ToolProfile(
        max_lines=50, max_chars=20_000, strategy="list",
        preserve_head=10, preserve_tail=5,
    ),
    "ls": ToolProfile(
        max_lines=100, max_chars=20_000, strategy="list",
        preserve_head=20, preserve_tail=5,
    ),
}


@dataclass
class ToolPrefilterConfig:
    """Configuration for tool output pre-filtering."""

    enabled: bool = True
    # Custom tool profiles (merged with defaults)
    tool_profiles: dict[str, ToolProfile] = field(default_factory=dict)
    # Global fallback limits (for unknown tools)
    fallback_max_lines: int = 300
    fallback_max_chars: int = 60_000
    # Minimum content length to trigger pre-filtering
    min_content_length: int = 500
    # Whether to add truncation markers
    add_truncation_markers: bool = True


class ToolPrefilter(Transform):
    """Pre-filter tool outputs before they enter the compression pipeline.

    Uses tool metadata to apply type-specific limits:
    - grep: max 50 lines, then SearchCompressor handles the rest
    - Read: max 500 lines, then ContentRouter decides
    - Bash: max 200 lines, detect type, then compress
    - Glob: max 50 items, alphabetical dedup
    """

    name = "tool_prefilter"

    def __init__(self, config: ToolPrefilterConfig | None = None) -> None:
        self.config = config or ToolPrefilterConfig()
        # Merge custom profiles with defaults
        self._profiles = dict(_DEFAULT_PROFILES)
        self._profiles.update(self.config.tool_profiles)

    def should_apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> bool:
        """Apply if there are tool messages with substantial content."""
        if not self.config.enabled:
            return False
        return any(
            msg.get("role") in ("tool", "function", "tool_result")
            and len(self._get_content_str(msg)) >= self.config.min_content_length
            for msg in messages[-30:]  # Check recent messages
        )

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Apply pre-filtering to tool output messages."""
        frozen_count = kwargs.get("frozen_message_count", 0)
        tokens_before = tokenizer.count_messages(messages)

        total_filtered = 0
        total_chars_saved = 0

        for i in range(frozen_count, len(messages)):
            msg = messages[i]
            if msg.get("role") not in ("tool", "function", "tool_result"):
                continue

            content = self._get_content_str(msg)
            if len(content) < self.config.min_content_length:
                continue

            # Get tool profile
            tool_name = msg.get("name", "") or self._infer_tool_name(msg)
            profile = self._profiles.get(tool_name)

            if profile is None:
                # Fallback: only filter if exceeds global limits
                lines = content.split("\n")
                if len(lines) <= self.config.fallback_max_lines and len(content) <= self.config.fallback_max_chars:
                    continue
                profile = ToolProfile(
                    max_lines=self.config.fallback_max_lines,
                    max_chars=self.config.fallback_max_chars,
                )

            # Apply pre-filter based on strategy
            filtered = self._apply_profile(content, profile)
            if filtered != content:
                self._set_content(msg, filtered)
                total_filtered += 1
                total_chars_saved += len(content) - len(filtered)

        tokens_after = tokenizer.count_messages(messages)
        transforms_applied = []
        if total_filtered > 0:
            transforms_applied.append(
                f"tool_prefilter:{total_filtered}_outputs"
            )
            logger.info(
                "ToolPrefilter: %d outputs pre-filtered, %d chars saved",
                total_filtered,
                total_chars_saved,
            )

        return TransformResult(
            messages=messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
            markers_inserted=[],
        )

    def _apply_profile(self, content: str, profile: ToolProfile) -> str:
        """Apply a tool profile's pre-filtering to content."""
        lines = content.split("\n")

        # Check if already within limits
        if len(lines) <= profile.max_lines and len(content) <= profile.max_chars:
            return content

        if profile.strategy == "search":
            return self._filter_search(lines, profile)
        elif profile.strategy == "code":
            return self._filter_code(lines, profile)
        elif profile.strategy == "list":
            return self._filter_list(lines, profile)
        elif profile.strategy == "log":
            return self._filter_log(lines, profile)
        else:
            return self._filter_auto(lines, profile)

    def _filter_search(self, lines: list[str], profile: ToolProfile) -> str:
        """Filter search results: prioritize error matches, keep head/tail."""
        if len(lines) <= profile.max_lines:
            return "\n".join(lines)

        # Score lines by priority patterns
        scored: list[tuple[int, str]] = []
        for i, line in enumerate(lines):
            score = 0
            for pattern in profile.priority_patterns:
                if re.search(pattern, line):
                    score += 10
            scored.append((score, line))

        # Keep: head + priority lines + tail
        head = lines[:profile.preserve_head]
        tail = lines[-profile.preserve_tail:]

        # Middle: sort by score, keep top N
        middle_lines = scored[profile.preserve_head:-profile.preserve_tail or len(scored)]
        middle_lines.sort(key=lambda x: x[0], reverse=True)
        budget = profile.max_lines - profile.preserve_head - profile.preserve_tail
        kept_middle = [line for _, line in middle_lines[:budget]]

        total_dropped = len(lines) - len(head) - len(kept_middle) - len(tail)
        result_lines = head + kept_middle

        if self.config.add_truncation_markers and total_dropped > 0:
            result_lines.append(
                f"\n[... {total_dropped} lines omitted — use SearchCompressor for ranked results ...]"
            )

        result_lines.extend(tail)
        return "\n".join(result_lines)

    def _filter_code(self, lines: list[str], profile: ToolProfile) -> str:
        """Filter code: preserve head (imports/signatures) and tail."""
        if len(lines) <= profile.max_lines:
            return "\n".join(lines)

        head = lines[:profile.preserve_head]
        tail = lines[-profile.preserve_tail:]
        total_dropped = len(lines) - profile.preserve_head - profile.preserve_tail

        # Keep lines near the middle that have definitions/structures
        middle_start = profile.preserve_head
        middle_end = len(lines) - profile.preserve_tail
        middle = lines[middle_start:middle_end]

        budget = profile.max_lines - profile.preserve_head - profile.preserve_tail
        if len(middle) <= budget:
            kept_middle = middle
            total_dropped = 0
        else:
            # Keep evenly spaced lines from middle
            step = max(1, len(middle) // budget)
            kept_middle = middle[::step][:budget]
            total_dropped = len(middle) - len(kept_middle)

        result_lines = head + kept_middle
        if self.config.add_truncation_markers and total_dropped > 0:
            result_lines.append(
                f"\n[... {total_dropped} lines omitted from middle ...]"
            )
        result_lines.extend(tail)
        return "\n".join(result_lines)

    def _filter_list(self, lines: list[str], profile: ToolProfile) -> str:
        """Filter list outputs: keep unique entries, respect limits."""
        if len(lines) <= profile.max_lines:
            return "\n".join(lines)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                unique_lines.append(line)

        if len(unique_lines) <= profile.max_lines:
            return "\n".join(unique_lines)

        # Still too many — keep head + tail
        head = unique_lines[:profile.preserve_head]
        tail = unique_lines[-profile.preserve_tail:]
        total_dropped = len(unique_lines) - profile.preserve_head - profile.preserve_tail

        result_lines = head
        if self.config.add_truncation_markers and total_dropped > 0:
            result_lines.append(
                f"[... {total_dropped} items omitted ...]"
            )
        result_lines.extend(tail)
        return "\n".join(result_lines)

    def _filter_log(self, lines: list[str], profile: ToolProfile) -> str:
        """Filter log outputs: prioritize errors/warnings, keep structure."""
        if len(lines) <= profile.max_lines:
            return "\n".join(lines)

        # Separate high-priority and low-priority lines
        high_priority: list[str] = []
        low_priority: list[str] = []

        for line in lines:
            is_important = False
            for pattern in profile.priority_patterns:
                if re.search(pattern, line):
                    is_important = True
                    break
            if is_important:
                high_priority.append(line)
            else:
                low_priority.append(line)

        # Always keep all high-priority lines (up to limit)
        budget = profile.max_lines
        result_lines = high_priority[:budget]
        remaining_budget = budget - len(result_lines)

        if remaining_budget > 0:
            # Fill with head/tail of low-priority
            head_count = min(profile.preserve_head, remaining_budget // 2)
            tail_count = min(profile.preserve_tail, remaining_budget - head_count)
            result_lines = (
                low_priority[:head_count]
                + result_lines
                + low_priority[-tail_count:] if tail_count > 0 else []
            )

        total_dropped = len(lines) - len(result_lines)
        if self.config.add_truncation_markers and total_dropped > 0:
            result_lines.append(
                f"[... {total_dropped} log lines omitted (kept errors/warnings) ...]"
            )

        return "\n".join(result_lines)

    def _filter_auto(self, lines: list[str], profile: ToolProfile) -> str:
        """Auto-detect content type and apply appropriate filter."""
        content_sample = "\n".join(lines[:20])

        # Detect grep-style output
        grep_pattern = re.compile(r"^[^:]+:\d+:")
        grep_matches = sum(1 for line in lines[:20] if grep_pattern.match(line))
        if grep_matches > 10:
            return self._filter_search(lines, profile)

        # Detect log-style output
        log_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}|^\[[\w]+\]|^(INFO|DEBUG|WARN|ERROR)")
        log_matches = sum(1 for line in lines[:20] if log_pattern.match(line))
        if log_matches > 10:
            return self._filter_log(lines, profile)

        # Detect list-style output (short lines, uniform structure)
        avg_line_len = sum(len(l) for l in lines[:50]) / min(50, len(lines))
        if avg_line_len < 80:
            return self._filter_list(lines, profile)

        # Default: code-style filtering
        return self._filter_code(lines, profile)

    def _get_content_str(self, msg: dict[str, Any]) -> str:
        """Extract string content from a message."""
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

    def _set_content(self, msg: dict[str, Any], new_content: str) -> None:
        """Set message content (handles string and list formats)."""
        current = msg.get("content", "")
        if isinstance(current, str):
            msg["content"] = new_content
        elif isinstance(current, list):
            for block in current:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = new_content
                    return
            current.append({"type": "text", "text": new_content})
        else:
            msg["content"] = new_content

    def _infer_tool_name(self, msg: dict[str, Any]) -> str:
        """Try to infer tool name from message metadata."""
        # Check various fields where tool name might be stored
        for key in ("name", "tool_name", "function_name"):
            val = msg.get(key, "")
            if val:
                return val
        return ""
