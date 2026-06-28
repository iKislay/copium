"""Error-driven compression for agent tool outputs.

When a tool call fails, compress the failure signal tightly — error type,
line number, suggestion — and discard the rest. Feed errors as structured
"error cards" that guide the agent to recovery instead of dumping verbose
stack traces.

Stack trace elision:
  - Keep top 2-3 frames (user code)
  - Elide framework/library frames (node_modules, std, java.lang.reflect)
  - Collapse repeated identical errors with count
  - Preserve security warnings (CVE/GHSA) in full

The core insight: error messages are prompts for the agent, not messages
for the user. If you write errors for humans ("Please try again"), the
agent stops. If you write errors for the agent (named error type +
context + NEXT_ACTIONS), it recovers autonomously.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from .base import Transform


# ============================================================================
# Error detection patterns
# ============================================================================

# Exit code patterns (Bash/command outputs)
_EXIT_CODE_PATTERNS = [
    re.compile(r"(?:^|\n)(?:.*?[:\s])?(?:exit(?:ed)?\s+(?:with\s+)?(?:code\s+)?|exit\s+code|exit\s+status|returned)\s*(\d+)", re.I),
    re.compile(r"\n(?:ERROR|FATAL|FAILED).*?exit(?:ed)?\s+(?:with\s+)?(?:code\s+)?(\d+)", re.I),
    re.compile(r"exited with code\s+(\d+)", re.I),
]

# Stack trace patterns per language
_STACK_TRACE_STARTS = [
    # Python
    re.compile(r"^(?:Traceback \(most recent call last\)|File \".*\", line \d+)", re.M),
    # Node.js / JavaScript (at functionName (path:line:col))
    re.compile(r"^\s*at\s+.*\s+\(.+:\d+:\d+\)", re.M),
    # Go
    re.compile(r"^goroutine \d+ \[.*\]:", re.M),
    # Rust
    re.compile(r"^thread\s+\".*\"\s+panicked\s+at", re.M),
    # Java
    re.compile(r"^(?:Exception|Caused by|at\s+[\w.$]+\([\w.]+:\d+\))", re.M),
]

# Framework/library frame patterns (to elide)
_FRAME_PATTERNS = [
    # Node.js
    re.compile(r"node_modules/"),
    re.compile(r"at\s+Module\._compile"),
    re.compile(r"at\s+Function\._load"),
    re.compile(r"at\s+Object\.<anonymous>"),
    # Python
    re.compile(r"site-packages/"),
    re.compile(r"lib/python\d"),
    re.compile(r"importlib/"),
    # Java
    re.compile(r"java\.lang\.reflect\."),
    re.compile(r"sun\.reflect\."),
    re.compile(r"org\.springframework\."),
    # Go
    re.compile(r"runtime/"),
    re.compile(r"net/http\."),
    # Rust
    re.compile(r"std::"),
    re.compile(r"core::"),
    re.compile(r"alloc::"),
]

# File:line reference pattern (useful context to keep)
_FILE_LINE_PATTERN = re.compile(r"([\w./\\-]+\.\w+):(\d+)")

# Error message patterns (high-signal lines)
_ERROR_PREFIXES = [
    "error", "Error", "ERROR",
    "fatal", "Fatal", "FATAL",
    "failed", "Failed", "FAILED",
    "exception", "Exception",
    "panic", "Panic", "PANIC",
    "warning", "Warning", "WARNING",
    "critical", "Critical", "CRITICAL",
    "E:",  # Rust compiler
]

# Security warning patterns (always preserve)
_SECURITY_PATTERNS = [
    re.compile(r"CVE-\d{4}-\d+", re.I),
    re.compile(r"GHSA-", re.I),
    re.compile(r"security\s+(?:advisory|vulnerability|warning)", re.I),
    re.compile(r"SECURITY\s+(?:ADVISORY|VULNERABILITY|WARNING)", re.I),
]

# Identical error collapse pattern
_IDENTICAL_ERROR_PATTERN = re.compile(
    r"^(.{20,}?)\s*(?:\(\d+ occurrences?\)|×\d+|\(\d+ times?\))",
    re.M,
)

# Build error patterns (TypeScript, Rust, GCC, Clang)
_BUILD_ERROR_PATTERNS = [
    # TypeScript: error TS2322: Type 'x' is not assignable to type 'y'
    re.compile(r"^(.+?):\s*(error TS\d+:\s*.+)$", re.M),
    # Rust: error[E0308]: mismatched types
    re.compile(r"^(.+?):\s*(error\[E\d+\]:\s*.+)$", re.M),
    # GCC/Clang: file.c:10:5: error: ...
    re.compile(r"^(.+?:\d+:\d+):\s*(error:\s*.+)$", re.M),
    # Generic: file:line: error: message
    re.compile(r"^(.+?:\d+):\s*(error:\s*.+)$", re.M),
]

# Docker build patterns
_DOCKER_LAYER_PATTERN = re.compile(
    r"^#\d+\s+\[\w+\s+\d+/\d+\]\s+(.+)$", re.M
)
_DOCKER_DOWNLOAD_PATTERN = re.compile(
    r"^(?:Downloading|Extracting|Pulling fs layer|Waiting|Download complete|"
    r"Pull complete|Verifying Checksum|Already exists)\s*.*$",
    re.M,
)
_DOCKER_PROGRESS_PATTERN = re.compile(
    r"^.*?(?:\d+\.\d+\s*[kMG]B/\d+\.\d+\s*[kMG]B|[\d.]+%|\[={>}\s*\]).*$",
    re.M,
)


@dataclass
class ErrorCard:
    """Structured error information extracted from tool output."""

    error_type: str  # e.g., "TypeError", "ExitCodeError", "BuildError"
    message: str  # First line of error message
    file: str | None = None  # Source file if known
    line: int | None = None  # Line number if known
    stack_frames: list[str] = field(default_factory=list)  # Top N frames
    exit_code: int | None = None  # Exit code if command failed
    next_actions: list[str] = field(default_factory=list)  # Suggested next steps
    raw_length: int = 0  # Original error output length
    grouped_count: int = 1  # Number of identical errors grouped
    grouped_files: list[str] = field(default_factory=list)  # Files with same error

    def to_marker(self, max_tokens: int = 200) -> str:
        """Convert to a compact retrieval marker for the LLM."""
        parts = [f"[Error: {self.error_type}"]

        if self.exit_code is not None:
            parts[0] += f" (exit {self.exit_code})"

        parts[0] += "]"
        parts.append(self.message[:120])

        if self.file:
            loc = self.file
            if self.line:
                loc += f":{self.line}"
            parts.append(f"  at {loc}")

        if self.stack_frames:
            frames_str = " → ".join(self.stack_frames[:3])
            parts.append(f"  {frames_str}")

        if self.next_actions:
            parts.append("  NEXT: " + "; ".join(self.next_actions[:2]))

        marker = "\n".join(parts)
        # Truncate if too long
        if len(marker) > max_tokens * 4:  # rough chars-per-token
            marker = marker[: max_tokens * 4] + "\n  [...truncated]"
        return marker


def _is_error_line(line: str) -> bool:
    """Check if a line is likely an error message."""
    stripped = line.strip()
    if not stripped:
        return False
    for prefix in _ERROR_PREFIXES:
        if stripped.startswith(prefix):
            return True
    # Check for exit code patterns
    if re.match(r"^(?:ERROR|FATAL|FAILED)\s*:", stripped):
        return True
    # Python exception patterns: "SomeError: message"
    if re.match(r"^\w+(?:Error|Exception|Warning)\s*:", stripped):
        return True
    return False


def _is_framework_frame(line: str) -> bool:
    """Check if a stack frame is from a framework/library."""
    # If the line contains a project path (e.g., /home/user/project/), it's not a framework frame
    if "/home/" in line or "/workspace/" in line or "/project/" in line:
        return False
    if re.search(r"/src/", line) and not re.search(r"node_modules/", line):
        return False
    for pattern in _FRAME_PATTERNS:
        if pattern.search(line):
            return True
    return False


def _is_security_warning(line: str) -> bool:
    """Check if a line contains a security warning."""
    for pattern in _SECURITY_PATTERNS:
        if pattern.search(line):
            return True
    return False


def _extract_file_line(text: str) -> tuple[str | None, int | None]:
    """Extract the first file:line reference from text."""
    # Try standard file:line pattern first
    match = _FILE_LINE_PATTERN.search(text)
    if match:
        return match.group(1), int(match.group(2))
    # Try Python File "...", line N pattern
    py_match = re.search(r'File "([^"]+)", line (\d+)', text)
    if py_match:
        return py_match.group(1), int(py_match.group(2))
    return None, None


def _detect_error_type(text: str) -> str:
    """Detect the error type from error output."""
    first_line = text.strip().split("\n")[0][:100]

    # Python exceptions
    py_match = re.match(r"^(\w+(?:\.\w+)*(?:Error|Exception|Warning))", first_line)
    if py_match:
        return py_match.group(1).split(".")[-1]

    # Node.js errors
    if "TypeError:" in first_line or "ReferenceError:" in first_line:
        return first_line.split(":")[0].strip()
    if "Error:" in first_line:
        return "Error"

    # Exit codes
    exit_match = re.search(r"exit(?:ed)?\s+(?:with\s+)?(?:code\s+)?(\d+)", first_line, re.I)
    if exit_match:
        code = int(exit_match.group(1))
        if code == 127:
            return "CommandNotFound"
        elif code == 1:
            return "GenericError"
        elif code == 137:
            return "OOMKilled"
        elif code == 139:
            return "Segfault"
        return f"ExitCode{code}"

    # Build errors
    if "BUILD FAILED" in text or "build failed" in text:
        return "BuildError"
    if "compilation failed" in text.lower():
        return "CompilationError"

    # Generic
    if "error" in first_line.lower():
        return "Error"
    if "fatal" in first_line.lower():
        return "FatalError"

    return "Error"


def _extract_stack_frames(text: str, max_frames: int = 3) -> list[str]:
    """Extract top stack frames, filtering out framework frames."""
    frames = []
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip framework frames
        if _is_framework_frame(line):
            continue

        # Extract file:line from frame
        match = _FILE_LINE_PATTERN.search(line)
        if match:
            file_path = match.group(1)
            line_num = match.group(2)
            # Shorten path
            parts = file_path.split("/")
            if len(parts) > 3:
                short_path = "/".join(parts[-3:])
            else:
                short_path = file_path
            frames.append(f"{short_path}:{line_num}")

            if len(frames) >= max_frames:
                break

    return frames


def _extract_next_actions(error_type: str, file: str | None, line: int | None) -> list[str]:
    """Generate suggested next actions based on error type."""
    actions = []

    if file:
        actions.append(f"Read {file}" + (f":{line}" if line else ""))

    if error_type in ("TypeError", "ReferenceError"):
        actions.append("Check variable definitions and types")
    elif error_type == "CommandNotFound":
        actions.append("Verify command exists and is in PATH")
    elif error_type == "OOMKilled":
        actions.append("Reduce memory usage or increase available memory")
    elif error_type == "Segfault":
        actions.append("Check for null pointer or buffer overflow")
    elif error_type in ("BuildError", "CompilationError"):
        actions.append("Review build output for specific error locations")
    elif error_type.startswith("ExitCode"):
        actions.append("Check command arguments and input data")

    return actions


def _compress_stack_trace(text: str, max_frames: int = 3) -> str:
    """Compress a stack trace, keeping only user-relevant frames."""
    lines = text.split("\n")
    result_lines = []
    in_trace = False
    kept_frames = 0
    total_frames = 0
    skipped_frames = 0

    for line in lines:
        stripped = line.strip()

        # Detect stack trace start
        for pattern in _STACK_TRACE_STARTS:
            if pattern.search(line):
                in_trace = True
                break

        if in_trace:
            total_frames += 1

            # Keep error message lines
            if _is_error_line(stripped):
                result_lines.append(line)
                continue

            # Keep security warnings
            if _is_security_warning(stripped):
                result_lines.append(line)
                continue

            # Check if this is a framework frame
            if _is_framework_frame(stripped):
                skipped_frames += 1
                continue

            # Keep user code frames
            if _FILE_LINE_PATTERN.search(stripped):
                if kept_frames < max_frames:
                    result_lines.append(line)
                    kept_frames += 1
                else:
                    skipped_frames += 1
            else:
                # Non-frame line in trace (e.g., "During handling...")
                result_lines.append(line)
        else:
            result_lines.append(line)

    # Add summary of hidden frames
    if skipped_frames > 0:
        result_lines.append(f"  (+ {skipped_frames} framework/internal frames hidden)")

    return "\n".join(result_lines)


def _collapse_identical_errors(text: str) -> str:
    """Collapse repeated identical error lines with a count."""
    lines = text.split("\n")
    result_lines: list[str] = []
    prev_stripped: str | None = None
    prev_raw: str = ""
    repeat_count = 0

    def _flush():
        nonlocal prev_stripped, prev_raw, repeat_count
        if repeat_count > 1 and prev_stripped:
            result_lines.append(f"{prev_stripped} (x{repeat_count})")
        elif prev_raw:
            result_lines.append(prev_raw)
        prev_stripped = None
        prev_raw = ""
        repeat_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped and stripped == prev_stripped:
            repeat_count += 1
        else:
            _flush()
            prev_stripped = stripped
            prev_raw = line
            repeat_count = 1

    _flush()
    return "\n".join(result_lines)


def _group_build_errors(text: str) -> str:
    """Group identical build errors across multiple files with counts.

    Before:
        src/a.ts: error TS2322: Type 'string' is not assignable to type 'number'
        src/b.ts: error TS2322: Type 'string' is not assignable to type 'number'
        src/c.ts: error TS2322: Type 'string' is not assignable to type 'number'

    After:
        error TS2322: Type 'string' is not assignable to type 'number' (3 files: src/a.ts, src/b.ts, src/c.ts)
    """
    # Try each build error pattern
    for pattern in _BUILD_ERROR_PATTERNS:
        matches = pattern.findall(text)
        if len(matches) < 2:
            continue

        # Group by error message
        error_groups: dict[str, list[str]] = {}
        for file_loc, error_msg in matches:
            error_msg_clean = error_msg.strip()
            if error_msg_clean not in error_groups:
                error_groups[error_msg_clean] = []
            error_groups[error_msg_clean].append(file_loc.strip())

        # Replace grouped errors
        for error_msg, files in error_groups.items():
            if len(files) < 2:
                continue

            # Remove original individual error lines
            for file_loc in files:
                # Escape special regex chars in the file location
                escaped_file = re.escape(file_loc)
                escaped_msg = re.escape(error_msg)
                line_pattern = re.compile(
                    rf"^{escaped_file}:\s*{escaped_msg}\s*$\n?", re.M
                )
                text = line_pattern.sub("", text)

            # Add grouped summary
            file_list = ", ".join(files[:5])
            if len(files) > 5:
                file_list += f", ... +{len(files) - 5} more"
            grouped_line = f"{error_msg} ({len(files)} files: {file_list})\n"
            text = text.rstrip() + "\n" + grouped_line

    return text


def _compress_docker_build(text: str) -> str:
    """Compress Docker build output.

    - Remove download progress lines
    - Deduplicate identical RUN steps
    - Keep layer summary and errors
    """
    lines = text.split("\n")
    result_lines: list[str] = []
    seen_layers: set[str] = set()
    download_count = 0
    progress_count = 0

    for line in lines:
        # Skip download progress
        if _DOCKER_DOWNLOAD_PATTERN.match(line):
            download_count += 1
            continue

        # Skip progress bars
        if _DOCKER_PROGRESS_PATTERN.match(line):
            progress_count += 1
            continue

        # Deduplicate identical Docker layers
        layer_match = _DOCKER_LAYER_PATTERN.match(line)
        if layer_match:
            layer_content = layer_match.group(1).strip()
            if layer_content in seen_layers:
                continue
            seen_layers.add(layer_content)

        result_lines.append(line)

    # Add summary of removed lines
    removed = download_count + progress_count
    if removed > 0:
        result_lines.append(
            f"  ({removed} download/progress lines removed)"
        )

    return "\n".join(result_lines)


def _normalize_compiler_errors(text: str) -> str:
    """Normalize compiler errors for better grouping.

    - Normalize absolute paths to relative
    - Remove timestamps
    - Collapse repeated warning patterns
    """
    lines = text.split("\n")
    result_lines: list[str] = []
    warning_counts: dict[str, int] = {}

    for line in lines:
        # Normalize absolute paths to relative
        # /home/user/project/src/file.ts -> src/file.ts
        line = re.sub(
            r"(?:/home/\w+/[\w.-]+/|/Users/\w+/[\w.-]+/|/workspace/[\w.-]+/)",
            "",
            line,
        )

        # Remove timestamps like [2026-06-28T10:30:00Z] or [10:30:00]
        line = re.sub(r"\[\d{4}-\d{2}-\d{2}T[\d:.]+Z?\]\s*", "", line)
        line = re.sub(r"\[\d{2}:\d{2}:\d{2}\]\s*", "", line)

        # Group repeated warnings
        warning_match = re.match(r"^(.+?:\d+:\d+:\s*warning:\s*.+)$", line)
        if warning_match:
            warning_msg = warning_match.group(1).strip()
            # Normalize path for grouping
            normalized = re.sub(r"^.+?:\d+:\d+:\s*", "", warning_msg)
            warning_counts[normalized] = warning_counts.get(normalized, 0) + 1
            if warning_counts[normalized] <= 2:
                result_lines.append(line)
            elif warning_counts[normalized] == 3:
                result_lines.append(f"  ... (repeated warning: {normalized})")
            # Skip further repeats
            continue

        result_lines.append(line)

    return "\n".join(result_lines)


@dataclass
class ErrorCompressorConfig:
    """Configuration for error-driven compression.

    When a tool call fails, compress the failure signal tightly and
    discard verbose output. Feed errors as structured "error cards"
    that guide the agent to recovery.

    The core insight: error messages are prompts for the agent. Written
    for humans ("Please try again"), the agent stops. Written for the
    agent (error type + context + NEXT_ACTIONS), it recovers
    autonomously.
    """

    enabled: bool = True

    # Stack trace elision
    max_stack_frames: int = 3  # Keep top N user-code frames
    preserve_framework_frames: bool = False  # Include framework frames

    # Security warnings (always preserved regardless of other settings)
    preserve_security_warnings: bool = True

    # Error card formatting
    max_error_card_tokens: int = 200  # Max tokens per error card marker
    include_next_actions: bool = True  # Add suggested next steps

    # Collapse repeated errors
    collapse_identical: bool = True  # Collapse N identical lines to "line (xN)"
    min_identical_to_collapse: int = 3  # Minimum repeats before collapsing

    # Build error grouping (TypeScript, Rust, GCC, Clang)
    group_build_errors: bool = True

    # Docker build output compression
    compress_docker_builds: bool = True

    # Compiler error normalization (path normalization, timestamp removal)
    normalize_compiler_errors: bool = True

    # Minimum error output length to compress (short outputs aren't worth it)
    min_length_to_compress: int = 150


class ErrorCompressor(Transform):
    """Error-driven compression for agent tool outputs.

    Detects error patterns in tool outputs (exit codes, stack traces,
    error messages) and replaces verbose error output with compact
    error cards that guide the agent to recovery.
    """

    name = "error_compressor"

    def __init__(self, config: ErrorCompressorConfig | None = None):
        self.config = config or ErrorCompressorConfig()

    def _has_error_signal(self, text: str) -> bool:
        """Check if text contains error signals worth compressing."""
        if len(text) < self.config.min_length_to_compress:
            return False

        # Check for exit codes
        for pattern in _EXIT_CODE_PATTERNS:
            if pattern.search(text):
                return True

        # Check for stack traces
        for pattern in _STACK_TRACE_STARTS:
            if pattern.search(text):
                return True

        # Check for error prefixes
        lines = text.split("\n")[:5]
        for line in lines:
            if _is_error_line(line):
                return True

        return False

    def _process_content(self, text: str) -> tuple[str, bool]:
        """Process a piece of content for error compression.

        Returns (compressed_text, was_compressed).
        """
        if not self._has_error_signal(text):
            return text, False

        original_length = len(text)
        result = text

        # Step 0: Normalize compiler errors (paths, timestamps)
        if self.config.normalize_compiler_errors:
            result = _normalize_compiler_errors(result)

        # Step 1: Collapse identical errors
        if self.config.collapse_identical:
            result = _collapse_identical_errors(result)

        # Step 2: Group build errors by type across files
        if self.config.group_build_errors:
            result = _group_build_errors(result)

        # Step 3: Compress Docker build output
        if self.config.compress_docker_builds:
            result = _compress_docker_build(result)

        # Step 4: Compress stack traces
        result = _compress_stack_trace(
            result, max_frames=self.config.max_stack_frames
        )

        # Step 3: Generate error card marker
        error_type = _detect_error_type(result)
        file_path, line_num = _extract_file_line(result)
        frames = _extract_stack_frames(result, self.config.max_stack_frames)
        exit_code = None

        exit_match = _EXIT_CODE_PATTERNS[0].search(text)
        if exit_match:
            exit_code = int(exit_match.group(1))

        # Extract first meaningful error line as message
        message = ""
        for line in result.split("\n"):
            stripped = line.strip()
            if stripped and _is_error_line(stripped):
                message = stripped[:150]
                break
        if not message:
            message = result.strip().split("\n")[0][:150]

        next_actions = []
        if self.config.include_next_actions:
            next_actions = _extract_next_actions(error_type, file_path, line_num)

        card = ErrorCard(
            error_type=error_type,
            message=message,
            file=file_path,
            line=line_num,
            stack_frames=frames,
            exit_code=exit_code,
            next_actions=next_actions,
            raw_length=original_length,
        )

        # Only compress if we actually saved something
        marker = card.to_marker(self.config.max_error_card_tokens)
        if len(marker) < len(text) * 0.8:
            return marker, True

        return text, False

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Apply error-driven compression to messages.

        Scans tool outputs for error signals and replaces verbose
        error output with compact error cards.
        """
        if not self.config.enabled:
            return TransformResult(
                messages=messages,
                tokens_before=tokenizer.count_messages(messages),
                tokens_after=tokenizer.count_messages(messages),
                transforms_applied=[],
            )

        frozen_count = kwargs.get("frozen_message_count", 0)
        tokens_before = tokenizer.count_messages(messages)

        result_messages: list[dict[str, Any]] = []
        transforms_applied: list[str] = []
        compressed_count = 0

        for i, msg in enumerate(messages):
            if i < frozen_count:
                result_messages.append(msg)
                continue

            role = msg.get("role", "")

            # Only process tool outputs (not user/assistant/system)
            if role not in ("tool", "tool_result", "function"):
                result_messages.append(msg)
                continue

            content = msg.get("content", "")
            if not isinstance(content, str) or len(content) < self.config.min_length_to_compress:
                result_messages.append(msg)
                continue

            compressed, was_compressed = self._process_content(content)

            if was_compressed:
                new_msg = dict(msg)
                new_msg["content"] = compressed
                result_messages.append(new_msg)
                transforms_applied.append("error_compressor:compress")
                compressed_count += 1
            else:
                result_messages.append(msg)

        tokens_after = tokenizer.count_messages(result_messages)

        if compressed_count > 0:
            import logging

            _logger = logging.getLogger(__name__)
            _logger.debug(
                "Error compressor: %d tool outputs compressed, %d -> %d tokens",
                compressed_count,
                tokens_before,
                tokens_after,
            )

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
        )
