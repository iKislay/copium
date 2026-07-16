"""Merge-only guard helpers for Claude Code's ``settings.json``.

Copium never owns ``~/.claude/settings.json`` — users keep custom API
endpoints (``ANTHROPIC_BASE_URL``), API keys, MCP servers, plugins and hooks
in it. Every Copium write must therefore be a surgical merge, every removal
must be limited to values Copium itself wrote, and pre-Copium originals must
be restorable on unwrap.

Three mechanisms live here:

* An **env ledger** (``~/.copium/claude_env_backup.json``) recording the
  pre-Copium value of each env key Copium rewrites, keyed by settings-file
  path. ``copium unwrap claude`` restores from it instead of blindly
  deleting keys.
* A **one-time backup** (``settings.json.copium-backup``) taken before the
  first Copium modification, so users can always recover by hand.
* A **deleted-key restorer** used after external tools (``rtk init``) touch
  the file, re-adding any keys they silently dropped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from copium.paths import ensure_workspace_dir, workspace_dir

_ENV_BACKUP_FILE = "claude_env_backup.json"

BACKUP_SUFFIX = ".copium-backup"

# Copium's proxy always binds a loopback host. Anything else in
# ANTHROPIC_BASE_URL (openrouter, freemodel.dev, corporate gateways, ...) is
# user-owned and must never be deleted by unwrap.
_LOOPBACK_URL_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(/.*)?$")


def is_copium_proxy_url(url: object) -> bool:
    """Return True when *url* plausibly points at a local Copium proxy."""
    return isinstance(url, str) and bool(_LOOPBACK_URL_RE.match(url.strip()))


def _ledger_path() -> Path:
    return workspace_dir() / _ENV_BACKUP_FILE


def _ledger_key(settings_path: Path) -> str:
    try:
        return str(settings_path.expanduser().resolve())
    except OSError:
        return str(settings_path)


def _load_ledger() -> dict[str, dict[str, Any]]:
    path = _ledger_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_ledger(ledger: dict[str, dict[str, Any]]) -> None:
    ensure_workspace_dir()
    _ledger_path().write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def record_env_original(settings_path: Path, key: str, original: Any) -> None:
    """Remember the pre-Copium value of env *key* (first record wins).

    ``original=None`` means the key was absent before Copium wrote it, so
    unwrap should delete it rather than restore a value.
    """
    ledger = _load_ledger()
    entry = ledger.setdefault(_ledger_key(settings_path), {})
    if key in entry:
        return  # keep the earliest (true pre-Copium) original
    entry[key] = original
    try:
        _save_ledger(ledger)
    except OSError:
        pass  # best-effort; unwrap falls back to the loopback heuristic


def pop_env_original(settings_path: Path, key: str) -> tuple[bool, Any]:
    """Return ``(recorded, original)`` for *key* and drop the ledger entry."""
    ledger = _load_ledger()
    entry = ledger.get(_ledger_key(settings_path))
    if not isinstance(entry, dict) or key not in entry:
        return False, None
    original = entry.pop(key)
    if not entry:
        ledger.pop(_ledger_key(settings_path), None)
    try:
        _save_ledger(ledger)
    except OSError:
        pass
    return True, original


def backup_settings_once(settings_path: Path) -> Path | None:
    """Copy ``settings.json`` to ``settings.json.copium-backup`` once.

    Only the pre-Copium state is preserved: an existing backup is never
    overwritten. Returns the backup path when a new backup was written.
    """
    if not settings_path.exists():
        return None
    backup = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
    if backup.exists():
        return None
    try:
        backup.write_bytes(settings_path.read_bytes())
    except OSError:
        return None
    return backup


def restore_deleted_keys(
    original: dict[str, Any], current: dict[str, Any], _prefix: str = ""
) -> list[str]:
    """Re-add keys present in *original* but deleted from *current*, in place.

    Recurses into dicts so a partially rewritten section (e.g. ``env`` with
    ``ANTHROPIC_BASE_URL`` dropped) gets its missing keys back while keeping
    everything the newer write legitimately added or changed. Lists and
    scalars that still exist are left as-is. Returns dotted paths of every
    restored key.
    """
    restored: list[str] = []
    for key, value in original.items():
        path = f"{_prefix}{key}"
        if key not in current:
            current[key] = value
            restored.append(path)
        elif isinstance(value, dict) and isinstance(current[key], dict):
            restored.extend(restore_deleted_keys(value, current[key], f"{path}."))
    return restored
