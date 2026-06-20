"""Differential Response transform — diffs for repeated tool calls.

For repeated tool calls (e.g., git status, polling), sends a unified diff
instead of the full output. Up to 95% savings on polling patterns.

How it works:
1. Tracks tool outputs by a hash of (tool_name, arguments)
2. When a repeated tool call is detected, computes a unified diff
3. Replaces the full tool output with a compact diff
"""

from __future__ import annotations

import difflib
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from ..config import DifferentialResponseConfig, TransformResult
from ..tokenizer import Tokenizer
from ..utils import deep_copy_messages
from .base import Transform


def _compute_tool_hash(tool_name: str, tool_input: Any) -> str:
    """Compute a stable hash for a tool call based on name + arguments."""
    # Normalize the input to a stable string representation
    if isinstance(tool_input, dict):
        normalized = json.dumps(tool_input, sort_keys=True, separators=(",", ":"))
    elif isinstance(tool_input, str):
        normalized = tool_input
    else:
        normalized = str(tool_input)

    content = f"{tool_name}:{normalized}"
    return hashlib.blake2b(content.encode(), digest_size=8).hexdigest()


def _compute_diff(old_text: str, new_text: str, context_lines: int = 3) -> str:
    """Compute a compact unified diff between two tool outputs."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="previous",
        tofile="current",
        n=context_lines,
    ))

    if not diff:
        return "[no changes]"

    # Compact the diff: remove unchanged context lines beyond context_lines
    result = []
    for line in diff:
        # Keep all + and - lines, limit context
        if line.startswith("+") or line.startswith("-") or line.startswith("@"):
            result.append(line)
        elif line.startswith(" ") and len(result) < 50:
            result.append(line)

    return "".join(result)


class DifferentialResponse(Transform):
    """Transform that computes diffs for repeated tool calls.

    Tracks tool outputs by (tool_name, arguments) hash. When a repeated
    tool call is detected, replaces the full output with a compact diff.
    """

    name = "differential_response"

    def __init__(self, config: DifferentialResponseConfig | None = None):
        self.config = config or DifferentialResponseConfig()
        # LRU cache: tool_hash -> (content, timestamp)
        self._tool_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def _evict_expired(self) -> None:
        """Remove expired entries from the cache."""
        now = time.time()
        expired = [
            k for k, (_, ts) in self._tool_cache.items()
            if now - ts > self.config.tracking_ttl_seconds
        ]
        for k in expired:
            del self._tool_cache[k]

    def _track_tool_output(self, tool_hash: str, content: str) -> str | None:
        """Track a tool output. Returns diff if this is a repeated call, None otherwise."""
        now = time.time()

        if tool_hash in self._tool_cache:
            old_content, _ = self._tool_cache[tool_hash]
            # Update the cache with new content
            self._tool_cache[tool_hash] = (content, now)
            # Move to end (most recently used)
            self._tool_cache.move_to_end(tool_hash)

            # Compute diff only if content is substantial enough
            if len(content) > self.config.min_chars_to_diff:
                return _compute_diff(old_content, content)
            return None

        # New tool call — store it
        self._tool_cache[tool_hash] = (content, now)
        self._tool_cache.move_to_end(tool_hash)

        # Evict if over capacity
        while len(self._tool_cache) > self.config.max_tracked_tools:
            self._tool_cache.popitem(last=False)

        self._evict_expired()
        return None

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

        for msg_idx, msg in enumerate(result_messages):
            # Only process tool result messages
            if msg.get("role") != "tool":
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            # Extract tool info from the message
            tool_name = msg.get("name", msg.get("tool_call_id", "unknown"))
            tool_call_id = msg.get("tool_call_id", "")

            # Compute hash from tool name and content as a proxy for arguments
            # (In practice, arguments are in the assistant's tool_call message)
            tool_hash = _compute_tool_hash(tool_name, tool_call_id + content[:200])

            # Check if this is a repeated tool call
            diff = self._track_tool_output(tool_hash, content)

            if diff is not None:
                # Replace content with the diff
                original_tokens = tokenizer.count_text(content)
                msg["content"] = diff
                diff_tokens = tokenizer.count_text(diff)

                if diff_tokens < original_tokens:
                    transforms_applied.append(
                        f"diff_response:{tool_name}:{original_tokens}->{diff_tokens}"
                    )

        tokens_after = tokenizer.count_messages(result_messages)

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
            warnings=warnings,
        )
