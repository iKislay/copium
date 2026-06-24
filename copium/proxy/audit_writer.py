"""Audit writer — appends per-request JSONL entries to ~/.copium/logs/audit.jsonl.

Plan §8c: every compression decision is written here so developers can grep,
pipe to jq, or build their own analysis on top.

Format (one JSON object per line):
  {
    "ts":          "2026-06-23T19:04:31Z",   # ISO-8601 UTC
    "req":         "req_7f3a2b",              # short request ID
    "provider":    "anthropic",
    "model":       "claude-sonnet-4-...",
    "path":        "/v1/messages",
    "transforms":  ["SmartCrusher", "CacheAligner"],
    "tokens_in":   4812,
    "tokens_out":  892,
    "savings":     0.815,                     # fraction 0–1
    "overhead_ms": 48.3,
    "cached":      false
  }

The writer is intentionally minimal — a single module-level lock guards the
file append so the async server can call it from multiple coroutines without
spawning a separate thread.  Errors are swallowed to preserve proxy liveness.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_log_path: Path | None = None
_enabled = True


def _default_audit_path() -> Path:
    try:
        from copium.paths import workspace_dir
        return workspace_dir() / "logs" / "audit.jsonl"
    except Exception:
        return Path.home() / ".copium" / "logs" / "audit.jsonl"


def configure(path: str | Path | None = None, *, enabled: bool = True) -> None:
    """Set the audit log path and enabled flag (call once at proxy startup)."""
    global _log_path, _enabled
    _enabled = enabled
    if path is not None:
        _log_path = Path(path)
    else:
        _log_path = _default_audit_path()


def _ensure_path() -> Path | None:
    global _log_path
    if _log_path is None:
        _log_path = _default_audit_path()
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        return _log_path
    except OSError as exc:
        logger.debug("audit_writer: cannot create log dir: %s", exc)
        return None


def record(
    *,
    request_id: str,
    provider: str = "unknown",
    model: str = "unknown",
    path: str = "/v1/messages",
    transforms: Sequence[str] | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    overhead_ms: float = 0.0,
    cached: bool = False,
    timestamp: str | None = None,
) -> None:
    """Append one JSONL entry.  Never raises — errors are logged at DEBUG."""
    if not _enabled:
        return
    log_path = _ensure_path()
    if log_path is None:
        return

    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tokens_in = max(0, int(tokens_in))
    tokens_out = max(0, int(tokens_out))
    savings = round(max(0.0, (tokens_in - tokens_out) / tokens_in), 6) if tokens_in > 0 else 0.0

    entry = {
        "ts": ts,
        "req": request_id,
        "provider": provider,
        "model": model,
        "path": path,
        "transforms": list(transforms) if transforms else [],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "savings": savings,
        "overhead_ms": round(overhead_ms, 2),
        "cached": cached,
    }

    line = json.dumps(entry, ensure_ascii=False)
    try:
        with _lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as exc:
        logger.debug("audit_writer: write failed: %s", exc)


def read_recent(n: int = 100, request_id: str | None = None) -> list[dict]:
    """Read the last *n* audit entries from disk (tail, newest last).

    If *request_id* is supplied, returns only entries matching that ID.
    Falls back to an empty list on any error.
    """
    log_path = _ensure_path()
    if log_path is None or not log_path.exists():
        return []
    try:
        lines: list[str] = []
        with _lock:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                # Efficient tail: read whole file into lines, slice last n.
                # audit.jsonl is expected to stay small (< 50k lines / ~10 MB).
                lines = f.readlines()

        entries: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if request_id is None or obj.get("req") == request_id:
                    entries.append(obj)
            except json.JSONDecodeError:
                continue

        return entries[-n:]
    except OSError as exc:
        logger.debug("audit_writer: read failed: %s", exc)
        return []
