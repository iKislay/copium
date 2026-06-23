"""Content preservation rules for shell output compression.

Plan §4.2 Layer 4: Contextual Preservation. For specific commands
that LLMs are trained on, preserve more structure to avoid the
'strangeness tax' — the phenomenon where compressed output confuses
LLMs because it doesn't match their training distribution.

Each rule maps a command pattern to a `PreservationRule` that controls
how much structure must be preserved when compressing that command's output.

The rules are consumed by:
  1. `QualityGate` (Gate 4) — to extract and verify critical markers.
  2. Content-type-aware compressors — to guide compression heuristics.

## Design

Rules are intentionally simple dataclasses rather than code, so they
can be serialised to config and overridden by users without code changes.
The actual compression decisions remain inside the compressors; this module
only documents what structure each compressor MUST preserve.

## References

- plans/04-beat-rtk.md §4.2 — full strangeness tax analysis
- copium/transforms/quality_gate.py — Gate 4 implementation
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PreservationRule:
    """Describes what structural elements must survive compression for a content type.

    Attributes:
        content_type: Canonical type identifier used by QualityGate.
        keep_headers: Preserve section header lines (e.g. 'On branch X').
        keep_file_paths: Always include full file paths in output.
        keep_hunk_headers: Preserve @@ ... @@ hunk position markers.
        keep_plus_minus: Preserve +/- line prefix markers.
        keep_errors: Always preserve error/failure lines.
        keep_summary: Preserve summary lines (pass/fail counts).
        drop_context_lines: Remove unchanged context lines (space-prefixed in diffs).
        drop_pass_lines: Drop individual passing test lines.
        drop_hints: Drop instructional hint lines (e.g. 'use git add ...').
        compress_descriptions: Compress but don't drop descriptive text.
        command_patterns: Shell command glob patterns this rule applies to.
    """

    content_type: str
    keep_headers: bool = False
    keep_file_paths: bool = True
    keep_hunk_headers: bool = False
    keep_plus_minus: bool = False
    keep_errors: bool = True
    keep_summary: bool = True
    drop_context_lines: bool = False
    drop_pass_lines: bool = False
    drop_hints: bool = False
    compress_descriptions: bool = False
    command_patterns: tuple[str, ...] = field(default_factory=tuple)


# ─── Preservation rules keyed by content_type ──────────────────────────────
#
# These are the canonical rules that must be satisfied for a compression step
# to pass QualityGate Gate 4. Compressors should use these as their minimum
# bar — they may preserve MORE structure, but never LESS.

PRESERVATION_RULES: dict[str, PreservationRule] = {
    # git status
    # Critical: branch name, file paths, status codes (M/A/D/?)
    # Safe to drop: instructional hints like "use git add ..."
    "git_status": PreservationRule(
        content_type="git_status",
        keep_headers=True,       # "On branch X", "Changes not staged for commit"
        keep_file_paths=True,    # Always show full paths
        drop_hints=True,         # Drop "(use 'git add ...')" advice
        compress_descriptions=True,  # Shorten but don't drop section headers
        command_patterns=("git status", "git status -s", "git status --short"),
    ),

    # git diff
    # Critical: hunk headers, +/- prefixes, file headers
    # Safe to drop: context lines (space-prefixed unchanged code)
    "git_diff": PreservationRule(
        content_type="git_diff",
        keep_hunk_headers=True,  # @@ -1,5 +1,7 @@
        keep_plus_minus=True,    # + added lines, - deleted lines
        keep_file_paths=True,    # diff --git a/... b/...
        drop_context_lines=True, # Lines starting with space (unchanged)
        command_patterns=("git diff", "git diff --cached", "git diff HEAD"),
    ),

    # pytest / cargo test / jest / vitest
    # Critical: pass/fail summary, failure details
    # Safe to drop: individual passing test lines
    "test_output": PreservationRule(
        content_type="test_output",
        keep_errors=True,        # Full failure output
        keep_summary=True,       # "X passed, Y failed"
        drop_pass_lines=True,    # Individual "PASSED test_name" lines
        command_patterns=("pytest", "python -m pytest", "cargo test", "jest", "vitest"),
    ),

    # Build output (make, cargo build, gcc, tsc, etc.)
    # Critical: error and warning lines with file:line references
    "build_output": PreservationRule(
        content_type="build_output",
        keep_errors=True,        # Error lines
        keep_summary=True,       # "N errors, M warnings"
        command_patterns=("make", "cargo build", "cargo check", "tsc", "gcc", "g++"),
    ),

    # grep / ripgrep search output
    # Critical: file paths, line numbers, matched text
    "grep": PreservationRule(
        content_type="grep",
        keep_file_paths=True,
        command_patterns=("grep", "grep -r", "grep -rn"),
    ),

    "ripgrep": PreservationRule(
        content_type="ripgrep",
        keep_file_paths=True,
        command_patterns=("rg", "rg -n", "rg --json"),
    ),
}


def rule_for_command(command: str) -> PreservationRule | None:
    """Look up the preservation rule for a given shell command string.

    Matches by checking if `command` starts with any of the rule's
    `command_patterns`. Returns the first match, or None if no rule
    applies.

    Examples:
        rule_for_command("git status -s")   → PRESERVATION_RULES["git_status"]
        rule_for_command("git diff HEAD~1") → PRESERVATION_RULES["git_diff"]
        rule_for_command("ls -la")          → None
    """
    command_stripped = command.strip()
    for rule in PRESERVATION_RULES.values():
        for pattern in rule.command_patterns:
            if command_stripped == pattern or command_stripped.startswith(pattern + " "):
                return rule
    return None


def content_type_for_command(command: str) -> str | None:
    """Return the content_type string for a given shell command, or None."""
    rule = rule_for_command(command)
    return rule.content_type if rule is not None else None


__all__ = [
    "PreservationRule",
    "PRESERVATION_RULES",
    "rule_for_command",
    "content_type_for_command",
]
