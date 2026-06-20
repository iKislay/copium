"""Proxy run mode helpers.

Canonical modes:
- token: prioritize compression (history may be rewritten for max savings)
- cache: prioritize provider prefix cache stability (freeze prior turns)
"""

from __future__ import annotations

import logging

logger = logging.getLogger("copium.proxy")

PROXY_MODE_TOKEN = "token"
PROXY_MODE_CACHE = "cache"

_MODE_ALIASES = {
    "token": PROXY_MODE_TOKEN,
    "token_mode": PROXY_MODE_TOKEN,
    "token_savings": PROXY_MODE_TOKEN,
    "token_copium": PROXY_MODE_TOKEN,
    "cache": PROXY_MODE_CACHE,
    "cache_mode": PROXY_MODE_CACHE,
    "cost_savings": PROXY_MODE_CACHE,
}


def normalize_proxy_mode(mode: str | None, *, default: str = PROXY_MODE_TOKEN) -> str:
    """Normalize a user-provided proxy mode to canonical token/cache values."""
    key = (mode or "").strip().lower()
    if not key:
        return default

    normalized = _MODE_ALIASES.get(key)
    if normalized is None:
        logger.warning("Unknown COPIUM_MODE '%s', falling back to '%s'", mode, default)
        return default

    if key != normalized:
        logger.info("COPIUM_MODE alias '%s' normalized to '%s'", mode, normalized)
    return normalized


def is_token_mode(mode: str | None) -> bool:
    """Return True when mode resolves to token mode."""
    return normalize_proxy_mode(mode) == PROXY_MODE_TOKEN


def is_cache_mode(mode: str | None) -> bool:
    """Return True when mode resolves to cache mode."""
    return normalize_proxy_mode(mode) == PROXY_MODE_CACHE
