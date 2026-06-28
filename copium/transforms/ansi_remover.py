"""ANSI escape code and terminal decoration removal transform.

Strips ANSI color codes, spinner sequences, cursor movement, and
other terminal decorations from tool outputs. Runs early in the
pipeline since ANSI noise can confuse content type detection.

Typical savings: 10-30% on terminal-heavy tool outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from .base import Transform


@dataclass
class ANSIRemoverConfig:
    """Configuration for ANSI/terminal decoration removal."""

    enabled: bool = True
    strip_colors: bool = True
    strip_spinners: bool = True
    strip_cursor_movement: bool = True
    strip_osc_sequences: bool = True
    preserve_structure: bool = True  # Keep newlines, indentation
    min_content_length: int = 20  # Don't process tiny outputs


# ANSI escape code patterns
_SGR_PATTERN = re.compile(r"\x1b\[[0-9;]*m")  # Select Graphic Rendition (colors/styles)
_CSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-HJKSTfh-l]")  # Cursor movement, erase
_OSC_PATTERN = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")  # Operating System Command
_GENERIC_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")  # Catch-all CSI
_SPINNER_PATTERN = re.compile(r"\r([^\n]*)")  # Carriage return overwrites
_PROGRESS_BAR = re.compile(
    r"[▓▒░█▌▍▎▏■□●○◐◑◒◓⣾⣽⣻⢿⡿⣟⣯⣷⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏|/\\-]+\s*\d+%",
    re.UNICODE,
)
_UNICODE_SPINNER = re.compile(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷◐◑◒◓]")


def strip_ansi(text: str) -> str:
    """Strip all ANSI escape codes from text.

    This is the main public utility — can be used standalone.
    """
    result = _SGR_PATTERN.sub("", text)
    result = _CSI_PATTERN.sub("", result)
    result = _OSC_PATTERN.sub("", result)
    result = _GENERIC_ESCAPE.sub("", result)
    return result


def strip_spinners(text: str) -> str:
    """Collapse carriage-return overwrites to final line only."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if "\r" in line:
            # Keep only the last \r segment (what the user would see)
            parts = line.split("\r")
            line = parts[-1]
        cleaned.append(line)
    return "\n".join(cleaned)


def strip_progress_bars(text: str) -> str:
    """Remove progress bar lines."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if _PROGRESS_BAR.search(line):
            continue
        # Skip lines that are only spinner characters
        stripped = line.strip()
        if stripped and all(_UNICODE_SPINNER.match(c) for c in stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


class ANSIRemover(Transform):
    """Strip ANSI escape codes and terminal decorations from tool outputs.

    Position: runs before ContentRouter since ANSI noise can confuse
    content type detection (e.g., colored JSON looks like plain text).
    """

    name = "ansi_remover"

    def __init__(self, config: ANSIRemoverConfig | None = None):
        self.config = config or ANSIRemoverConfig()

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Strip ANSI from all tool result content."""
        if not self.config.enabled:
            return TransformResult(messages=messages, transforms_applied=[])

        frozen_count = kwargs.get("frozen_message_count", 0)
        modified = False
        tokens_saved = 0

        for i, msg in enumerate(messages):
            if i < frozen_count:
                continue

            # Only process tool results and content with potential ANSI
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role not in ("tool", "user") or not isinstance(content, str):
                # Check multi-part content
                if isinstance(content, list):
                    new_parts, changed = self._process_parts(content)
                    if changed:
                        msg["content"] = new_parts
                        modified = True
                continue

            if len(content) < self.config.min_content_length:
                continue

            # Check if content has any ANSI sequences
            if "\x1b" not in content and "\r" not in content:
                continue

            original_len = len(content)
            cleaned = self._clean(content)

            if cleaned != content:
                msg["content"] = cleaned
                modified = True
                # Estimate token savings (chars/4 approximation)
                tokens_saved += (original_len - len(cleaned)) // 4

        transforms = ["ansi_remover"] if modified else []
        return TransformResult(
            messages=messages,
            transforms_applied=transforms,
            tokens_saved=tokens_saved,
        )

    def _process_parts(
        self, parts: list[Any]
    ) -> tuple[list[Any], bool]:
        """Process multi-part content (Anthropic format)."""
        changed = False
        new_parts = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") in ("text", "tool_result"):
                text_key = "text" if part.get("type") == "text" else "content"
                text = part.get(text_key, "")
                if isinstance(text, str) and ("\x1b" in text or "\r" in text):
                    cleaned = self._clean(text)
                    if cleaned != text:
                        part = {**part, text_key: cleaned}
                        changed = True
            new_parts.append(part)
        return new_parts, changed

    def _clean(self, text: str) -> str:
        """Apply all configured cleaning passes."""
        result = text

        if self.config.strip_colors:
            result = strip_ansi(result)

        if self.config.strip_spinners:
            result = strip_spinners(result)
            result = strip_progress_bars(result)

        if self.config.strip_cursor_movement:
            # Already handled by strip_ansi CSI patterns
            pass

        if self.config.strip_osc_sequences:
            # Already handled by strip_ansi OSC pattern
            pass

        if self.config.preserve_structure:
            # Collapse multiple blank lines into one
            result = re.sub(r"\n{3,}", "\n\n", result)

        return result
