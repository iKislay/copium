"""OpenCode Go integration: model registry and auth loader.

OpenCode Go (https://opencode.ai/go) is a low-cost subscription upstream
that serves curated open coding models over an OpenAI-compatible API at
``https://opencode.ai/zen/go/v1/chat/completions``.

This module is the single source of truth for:

* the set of model IDs that should route to the Go upstream (so the proxy
  handler and the ``copium wrap opencode`` CLI stay in sync), and
* loading the Go API key from ``~/.local/share/opencode/auth.json`` (the
  ``opencode-go`` entry written by opencode's ``/connect`` command).

The auth key is never written into ``opencode.json`` — it stays on disk in
``auth.json`` and is injected by the proxy at the upstream hop, keeping the
secret out of the opencode client process's config file.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Authoritative model IDs served by the Go upstream. Confirmed against the
# live ``https://opencode.ai/zen/go/v1/models`` endpoint. All of these are
# OpenAI-compatible (``/v1/chat/completions``); the Anthropic-endpoint Go
# models (Qwen3.7 Max/Plus, MiniMax M3/M2.7) are intentionally NOT included
# here yet — routing them requires the Anthropic ``/v1/messages`` path, which
# is deferred. See ``plans/`` for the follow-up.
OPENCODE_GO_MODELS: frozenset[str] = frozenset(
    {
        "glm-5.2",
        "glm-5.1",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "mimo-v2.5",
        "mimo-v2.5-pro",
    }
)

# Default location of opencode's auth store. opencode's ``/connect`` command
# writes ``{"opencode-go": {"type": "api", "key": "sk-..."}}`` here.
_DEFAULT_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"

# Cache TTL for the loaded key. We re-stat the file periodically so key
# rotations (e.g. user re-runs ``/connect``) are picked up without a proxy
# restart. Short enough for interactive flows, long enough to avoid stat
# churn on every request.
_AUTH_CACHE_TTL_SECONDS = 30.0


def is_opencode_go_model(model_id: str) -> bool:
    """Return True if ``model_id`` should route to the OpenCode Go upstream."""
    return model_id in OPENCODE_GO_MODELS


def opencode_auth_path() -> Path:
    """Return the path to opencode's auth.json (overridable via env)."""
    env_override = os.environ.get("OPENCODE_AUTH_FILE")
    if env_override:
        return Path(env_override).expanduser()
    return _DEFAULT_AUTH_PATH


class OpenCodeGoAuthLoader:
    """Cached loader for the OpenCode Go API key from opencode's auth.json.

    Thread-safe enough for the proxy's async usage: the key is a short string
    and lookups are idempotent. Worst case on a concurrent refresh is a few
    redundant stats/reads, never a torn value.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or opencode_auth_path()
        self._cached_key: str | None = None
        self._cache_time: float = 0.0
        self._last_mtime: float = 0.0

    def _is_fresh(self, now: float) -> bool:
        if self._cached_key is None:
            return False
        if now - self._cache_time > _AUTH_CACHE_TTL_SECONDS:
            return False
        return True

    def _read_key(self) -> str | None:
        """Read and parse the auth.json file, returning the Go key or None."""
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("opencode auth.json is not valid JSON: %s", self._path)
            return None
        entry = data.get("opencode-go")
        if not isinstance(entry, dict):
            return None
        key = entry.get("key")
        if isinstance(key, str) and key:
            return key
        return None

    def get_key(self, *, force_refresh: bool = False) -> str | None:
        """Return the cached Go API key, refreshing from disk if stale.

        Returns ``None`` when the auth file or the ``opencode-go`` entry is
        absent (e.g. the user hasn't run ``/connect`` for Go yet). Callers
        should treat ``None`` as "no Go auth available" and fall back to the
        standard OpenAI upstream.
        """
        now = time.monotonic()
        if not force_refresh and self._is_fresh(now):
            return self._cached_key

        # Stat the file so a manual key rotation is picked up even before the
        # TTL expires. Cheaper than re-reading on every request.
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            # File gone — clear the cache so a later re-create is noticed.
            if self._cached_key is not None:
                logger.info("opencode auth.json removed; clearing Go key cache")
            self._cached_key = None
            self._cache_time = now
            return None

        if not force_refresh and self._cached_key is not None and mtime == self._last_mtime:
            # File unchanged since last read — just refresh the TTL clock.
            self._cache_time = now
            return self._cached_key

        key = self._read_key()
        self._cached_key = key
        self._cache_time = now
        self._last_mtime = mtime
        if key is None:
            logger.debug(
                "No opencode-go key found in %s (run /connect in opencode first)",
                self._path,
            )
        return key


# Module-level singleton — the proxy process is long-lived and shares one
# loader. ``get_opencode_go_key`` is the convenience accessor used by the
# request handlers.
_default_loader: OpenCodeGoAuthLoader | None = None


def get_opencode_go_key(*, force_refresh: bool = False) -> str | None:
    """Return the Go API key from the module-level auth loader."""
    global _default_loader
    if _default_loader is None:
        _default_loader = OpenCodeGoAuthLoader()
    return _default_loader.get_key(force_refresh=force_refresh)


def reset_auth_loader() -> None:
    """Reset the module-level auth loader (for tests)."""
    global _default_loader
    _default_loader = None
