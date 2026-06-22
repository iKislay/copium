"""Output compression transform — compresses assistant responses.

Compresses what the model *writes back* (not just input). Drops ceremony,
restate code, skips deep thinking on routine steps. This is a huge untapped
area — most compression tools focus only on input tokens.

Savings: 30-74% on output tokens depending on content type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..config import OutputCompressorConfig, TransformResult
from ..tokenizer import Tokenizer
from ..utils import deep_copy_messages
from .base import Transform


# Compiled regex cache
_filler_re: list[re.Pattern[str]] | None = None
_meta_re: list[re.Pattern[str]] | None = None


def _compile_patterns(config: OutputCompressorConfig) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    global _filler_re, _meta_re
    if _filler_re is None:
        _filler_re = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in config.filler_phrases]
    if _meta_re is None:
        _meta_re = [re.compile(p) for p in config.meta_patterns]
    return _filler_re, _meta_re


def _remove_filler(text: str, patterns: list[re.Pattern[str]]) -> str:
    """Remove filler phrases from the beginning of the text."""
    for pattern in patterns:
        text = pattern.sub("", text, count=1)
    return text.strip()


def _remove_meta(text: str, patterns: list[re.Pattern[str]]) -> str:
    """Remove meta-commentary lines."""
    for pattern in patterns:
        text = pattern.sub("", text)
    return text


def _dedup_paragraphs(text: str) -> str:
    """Remove exact duplicate paragraphs."""
    paragraphs = text.split("\n\n")
    seen: set[str] = set()
    result: list[str] = []
    for para in paragraphs:
        normalized = para.strip()
        if normalized and normalized in seen:
            continue
        seen.add(normalized)
        result.append(para)
    return "\n\n".join(result)


def _trim_code_blocks(text: str, max_lines: int) -> str:
    """Trim overly long code blocks."""
    if max_lines <= 0:
        return text

    def _replace_block(match: re.Match[str]) -> str:
        block = match.group(0)
        lines = block.split("\n")
        if len(lines) <= max_lines + 2:  # +2 for opening/closing fences
            return block
        # Keep first max_lines lines + closing fence
        kept = lines[: max_lines + 1]
        kept.append(f"... ({len(lines) - max_lines - 1} lines truncated)")
        return "\n".join(kept)

    return re.sub(r"```[\s\S]*?```", _replace_block, text)


def _remove_duplicate_trailing(text: str) -> str:
    """Remove trailing sections that duplicate earlier content."""
    lines = text.rstrip().split("\n")
    if len(lines) < 4:
        return text

    # Look for the pattern where the last paragraph is a restatement
    # of the first paragraph (common in LLM output)
    first_meaningful = ""
    for line in lines[:10]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("```"):
            first_meaningful = stripped.lower()
            break

    if not first_meaningful:
        return text

    # Check if last few lines contain the same content
    last_lines = "\n".join(lines[-5:]).lower()
    if first_meaningful[:30] in last_lines and len(lines) > 10:
        # Find where the repetition starts
        for i in range(len(lines) - 5, max(0, len(lines) // 2), -1):
            candidate = lines[i].strip().lower()
            if candidate and candidate[:30] == first_meaningful[:30]:
                return "\n".join(lines[:i]).rstrip()

    return text.rstrip()


class OutputCompressor(Transform):
    """Compresses assistant output messages.

    This transform targets assistant messages in the conversation history,
    removing filler, deduplicating repeated content, and trimming verbose
    sections. It operates on the OUTPUT tokens (what the model writes),
    not the input tokens.
    """

    name = "output_compressor"

    def __init__(self, config: OutputCompressorConfig | None = None):
        self.config = config or OutputCompressorConfig()

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

        filler_patterns, meta_patterns = _compile_patterns(self.config)

        for msg_idx, msg in enumerate(result_messages):
            # Only compress assistant messages (model output)
            if msg.get("role") != "assistant":
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            original_tokens = tokenizer.count_text(content)
            if original_tokens < self.config.min_tokens_to_compress:
                continue

            compressed = content

            # Step 1: Remove filler phrases
            new_compressed = _remove_filler(compressed, filler_patterns)
            if new_compressed != compressed:
                transforms_applied.append(f"output:filler:{msg_idx}")
                compressed = new_compressed

            # Step 2: Remove meta-commentary
            new_compressed = _remove_meta(compressed, meta_patterns)
            if new_compressed != compressed:
                transforms_applied.append(f"output:meta:{msg_idx}")
                compressed = new_compressed

            # Step 3: Dedup paragraphs
            if self.config.dedup_paragraphs:
                new_compressed = _dedup_paragraphs(compressed)
                if new_compressed != compressed:
                    transforms_applied.append(f"output:dedup:{msg_idx}")
                    compressed = new_compressed

            # Step 4: Trim code blocks
            if self.config.max_code_block_lines > 0:
                new_compressed = _trim_code_blocks(compressed, self.config.max_code_block_lines)
                if new_compressed != compressed:
                    transforms_applied.append(f"output:trim:{msg_idx}")
                    compressed = new_compressed

            # Step 5: Remove duplicate trailing sections
            new_compressed = _remove_duplicate_trailing(compressed)
            if new_compressed != compressed:
                transforms_applied.append(f"output:trailing:{msg_idx}")
                compressed = new_compressed

            if compressed != content:
                msg["content"] = compressed
                saved = original_tokens - tokenizer.count_text(compressed)
                if saved > 0:
                    transforms_applied.append(f"output:compressed:{msg_idx}:saved={saved}")

        tokens_after = tokenizer.count_messages(result_messages)

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
            warnings=warnings,
        )
