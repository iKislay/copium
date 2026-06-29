"""Claude Code hook integration — bridge Copium with Claude Code's hook system.

Provides hook scripts and settings generation for Claude Code's PreCompact
and PostCompact hook events. When Claude Code fires auto-compaction, Copium
captures the session state and restores critical context after compaction.

Usage:
    # Generate Claude Code hook configuration
    copium init --hooks claude-code

    # Or use programmatically
    from copium.hooks.claude_code import generate_hook_settings, capture_state, inject_context
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default paths
CLAUDE_SETTINGS_DIR = Path.home() / ".claude"
CLAUDE_SETTINGS_FILE = CLAUDE_SETTINGS_DIR / "settings.json"
COPIUM_HOOKS_DIR = Path.home() / ".copium" / "hooks"


@dataclass
class ClaudeCodeHookConfig:
    """Configuration for Claude Code hook integration."""

    settings_dir: Path = field(default_factory=lambda: CLAUDE_SETTINGS_DIR)
    hooks_dir: Path = field(default_factory=lambda: COPIUM_HOOKS_DIR)
    checkpoint_dir: Path = field(
        default_factory=lambda: Path.home() / ".copium" / "checkpoints"
    )
    # What to capture in PreCompact
    capture_file_paths: bool = True
    capture_decisions: bool = True
    capture_tool_outputs: bool = True
    capture_messages: bool = True
    # What to inject in PostCompact
    inject_file_paths: bool = True
    inject_decisions: bool = True
    inject_ccr_refs: bool = True
    # Limits
    max_checkpoint_tokens: int = 50_000
    max_recovery_tokens: int = 30_000


def generate_hook_settings(config: ClaudeCodeHookConfig | None = None) -> dict[str, Any]:
    """Generate Claude Code settings.json hook configuration.

    Creates settings that integrate Copium's pre/post compaction hooks
    with Claude Code's native hook system.

    Returns:
        dict suitable for writing to .claude/settings.json
    """
    config = config or ClaudeCodeHookConfig()

    # Ensure hooks directory exists
    config.hooks_dir.mkdir(parents=True, exist_ok=True)

    settings = {
        "hooks": {
            "PreCompact": [
                {
                    "command": f"python -m copium.hooks.claude_code capture "
                    f"--checkpoint-dir {config.checkpoint_dir}",
                    "description": "Copium: Save session state before compaction",
                    "timeout": 10000,
                }
            ],
            "PostCompact": [
                {
                    "command": f"python -m copium.hooks.claude_code recover "
                    f"--checkpoint-dir {config.checkpoint_dir}",
                    "description": "Copium: Restore critical context after compaction",
                    "timeout": 10000,
                }
            ],
        }
    }

    return settings


def write_hook_settings(
    config: ClaudeCodeHookConfig | None = None,
    merge: bool = True,
) -> Path:
    """Write Claude Code hook settings to settings.json.

    Args:
        config: Hook configuration.
        merge: If True, merge with existing settings. If False, overwrite hooks.

    Returns:
        Path to the written settings file.
    """
    config = config or ClaudeCodeHookConfig()
    settings_file = config.settings_dir / "settings.json"

    # Load existing settings if merging
    existing: dict[str, Any] = {}
    if merge and settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Generate new hook settings
    new_settings = generate_hook_settings(config)

    # Merge hooks
    if merge and "hooks" in existing:
        for event, hooks in new_settings["hooks"].items():
            existing_hooks = existing["hooks"].get(event, [])
            # Remove any existing Copium hooks
            existing_hooks = [
                h for h in existing_hooks if "copium" not in h.get("command", "").lower()
            ]
            existing_hooks.extend(hooks)
            existing.setdefault("hooks", {})[event] = existing_hooks
    else:
        existing.update(new_settings)

    # Write settings
    config.settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(existing, indent=2) + "\n",
        encoding="utf-8",
    )

    logger.info("Claude Code hook settings written to %s", settings_file)
    return settings_file


def capture_state(
    session_id: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    """Capture session state for PreCompact hook.

    Called by Claude Code's PreCompact hook event. Reads the current
    session transcript and saves a checkpoint.

    Args:
        session_id: Session identifier (from environment or auto-detected).
        messages: Current messages (if available from hook data).
        checkpoint_dir: Where to store checkpoints.

    Returns:
        Checkpoint summary dict.
    """
    from ..proxy.pre_compact_hook import CheckpointConfig, PreCompactHook
    from ..proxy.compaction_detector import CompactionEvent

    checkpoint_dir = checkpoint_dir or Path.home() / ".copium" / "checkpoints"
    session_id = session_id or os.environ.get("CLAUDE_SESSION_ID", f"claude-{int(time.time())}")

    config = CheckpointConfig(checkpoint_dir=checkpoint_dir)
    hook = PreCompactHook(config)

    # If messages not provided, try to read from Claude's transcript
    if messages is None:
        messages = _read_claude_transcript(session_id)

    # Create a synthetic compaction event
    token_estimate = sum(len(str(m.get("content", ""))) // 4 for m in messages)
    event = CompactionEvent(
        session_id=session_id,
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4"),
        token_usage=token_estimate,
        context_window=200_000,
        threshold=0.835,
        usage_pct=token_estimate / 200_000,
    )

    import asyncio

    checkpoint = asyncio.run(hook.on_compaction_imminent(event, messages))

    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "session_id": checkpoint.session_id,
        "files": len(checkpoint.file_paths_mentioned),
        "decisions": len(checkpoint.decisions),
        "tool_hashes": len(checkpoint.tool_output_hashes),
    }


def inject_context(
    session_id: str | None = None,
    checkpoint_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Inject recovered context for PostCompact hook.

    Called by Claude Code's PostCompact hook event. Loads the most recent
    checkpoint and generates recovery messages.

    Args:
        session_id: Session identifier.
        checkpoint_dir: Where checkpoints are stored.

    Returns:
        List of recovery messages to inject.
    """
    from ..proxy.post_compact_recovery import PostCompactRecovery, RecoveryConfig

    checkpoint_dir = checkpoint_dir or Path.home() / ".copium" / "checkpoints"
    session_id = session_id or os.environ.get("CLAUDE_SESSION_ID", f"claude-{int(time.time())}")

    config = RecoveryConfig(checkpoint_dir=checkpoint_dir)
    recovery = PostCompactRecovery(config)

    messages, result = recovery.recover(session_id)

    if result.success:
        logger.info(
            "Recovered %d messages for session %s "
            "(files: %d, decisions: %d)",
            result.messages_injected,
            session_id,
            result.file_paths_restored,
            result.decisions_restored,
        )

    return messages


def _read_claude_transcript(session_id: str) -> list[dict[str, Any]]:
    """Try to read Claude Code's JSONL transcript for a session.

    Claude Code stores transcripts at ~/.claude/projects/<project>/sessions/<id>.jsonl
    """
    claude_dir = Path.home() / ".claude"
    messages: list[dict[str, Any]] = []

    # Search for session transcripts
    for projects_dir in [claude_dir / "projects"]:
        if not projects_dir.exists():
            continue
        for session_file in projects_dir.rglob(f"*{session_id}*.jsonl"):
            try:
                for line in session_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        messages.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                continue

    return messages


if __name__ == "__main__":
    """CLI entry point for Claude Code hook integration."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m copium.hooks.claude_code [capture|recover|init]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "capture":
        result = capture_state()
        print(json.dumps(result, indent=2))
    elif command == "recover":
        messages = inject_context()
        print(json.dumps(messages, indent=2))
    elif command == "init":
        path = write_hook_settings()
        print(f"Hook settings written to {path}")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
