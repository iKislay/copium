"""Hook compression commands for Claude Code PreToolUse/PostToolUse hooks.

These commands are registered as Claude Code hooks to compress tool output
before it reaches the LLM context window. They read from stdin and write
to stdout (or modify the JSON tool_input/tool_result blocks in-place).

Plan §8.2.5: Hook for Read tool, Hook for Grep tool.

Hook registration examples (added to ~/.claude/settings.json):

  {
    "hooks": {
      "PreToolUse": [
        {
          "matcher": "Read",
          "hooks": [{"type": "command", "command": "copium compress-read --max-lines 200"}]
        },
        {
          "matcher": "Grep",
          "hooks": [{"type": "command", "command": "copium compress-search --max-results 50"}]
        }
      ]
    }
  }

These hooks run in the Claude Code shell hook pipeline. They receive a JSON
object on stdin (the tool_input or tool_result block) and must write a
(possibly modified) JSON object to stdout.

Note: These commands operate on the hook input JSON format used by Claude
Code's hook system. They do not modify the proxy's tool_result compression,
which happens separately via the content_router.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .main import main


@main.command("compress-read")
@click.option(
    "--max-lines",
    default=200,
    type=int,
    help="Maximum number of lines to keep in a file read (default: 200)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Log compression actions to stderr",
)
def compress_read(max_lines: int, verbose: bool) -> None:
    """Compress large file reads in Claude Code's Read tool hook.

    \\b
    Reads a Claude Code tool hook JSON object from stdin, applies
    line-count truncation to large file reads, and writes the
    (possibly modified) JSON object to stdout.

    \\b
    This is designed to be used as a Claude Code PreToolUse hook for
    the Read tool. Register it in ~/.claude/settings.json:

    \\b
        {
          "hooks": {
            "PreToolUse": [{
              "matcher": "Read",
              "hooks": [{"type": "command",
                         "command": "copium compress-read --max-lines 200"}]
            }]
          }
        }

    \\b
    Files under the line limit are passed through unchanged (zero overhead).
    Files over the limit get a truncation notice appended so the LLM knows
    the read was partial.
    """
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Not valid JSON — pass through unchanged (safety-first)
        sys.stdout.write(raw if "raw" in dir() else "")
        return

    # Claude Code tool hook format: {"tool_input": {...}, "tool_result": {...}}
    # For PreToolUse on Read, we get tool_input with "file_path" etc.
    # For PostToolUse on Read, we get tool_result with "content"
    # Handle both.

    modified = False

    # PostToolUse: compress tool_result content
    tool_result = payload.get("tool_result")
    if isinstance(tool_result, dict):
        content = tool_result.get("content", "")
        if isinstance(content, str):
            lines = content.splitlines()
            if len(lines) > max_lines:
                kept = lines[:max_lines]
                omitted = len(lines) - max_lines
                kept.append(
                    f"\n[... {omitted} lines omitted by copium compress-read "
                    f"(--max-lines {max_lines}). Use copium_retrieve or read with "
                    f"offset to see more. ...]"
                )
                payload["tool_result"]["content"] = "\n".join(kept)
                modified = True
                if verbose:
                    file_path = payload.get("tool_input", {}).get("file_path", "unknown")
                    print(
                        f"compress-read: {file_path}: kept {max_lines}/{len(lines)} lines",
                        file=sys.stderr,
                    )

    sys.stdout.write(json.dumps(payload))
    if modified and verbose:
        pass  # already logged above


@main.command("compress-search")
@click.option(
    "--max-results",
    default=50,
    type=int,
    help="Maximum number of search results to keep (default: 50)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Log compression actions to stderr",
)
def compress_search(max_results: int, verbose: bool) -> None:
    """Compress large search results in Claude Code's Grep tool hook.

    \\b
    Reads a Claude Code tool hook JSON object from stdin, applies
    result-count truncation to large search results, and writes the
    (possibly modified) JSON object to stdout.

    \\b
    This is designed to be used as a Claude Code PreToolUse hook for
    the Grep tool. Register it in ~/.claude/settings.json:

    \\b
        {
          "hooks": {
            "PreToolUse": [{
              "matcher": "Grep",
              "hooks": [{"type": "command",
                         "command": "copium compress-search --max-results 50"}]
            }]
          }
        }

    \\b
    Results under the limit are passed through unchanged (zero overhead).
    Truncated results get a summary notice so the LLM knows how many matches
    were omitted and where to look for more.
    """
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        sys.stdout.write(raw if "raw" in dir() else "")
        return

    modified = False

    tool_result = payload.get("tool_result")
    if isinstance(tool_result, dict):
        content = tool_result.get("content", "")
        if isinstance(content, str):
            lines = [ln for ln in content.splitlines() if ln.strip()]
            if len(lines) > max_results:
                kept_lines = lines[:max_results]
                omitted = len(lines) - max_results
                kept_lines.append(
                    f"\n[... {omitted} matches omitted by copium compress-search "
                    f"(--max-results {max_results}). Use a more specific pattern "
                    f"or increase --max-results to see all. ...]"
                )
                payload["tool_result"]["content"] = "\n".join(kept_lines)
                modified = True
                if verbose:
                    pattern = payload.get("tool_input", {}).get("pattern", "unknown")
                    print(
                        f"compress-search: pattern={pattern!r}: "
                        f"kept {max_results}/{len(lines)} results",
                        file=sys.stderr,
                    )

    sys.stdout.write(json.dumps(payload))
