"""First-request toast — §10a.

After the very *first* request is successfully compressed through the Copium
proxy, emit a one-time celebratory message to:

1. The proxy log (always) — so ``copium logs`` shows it.
2. stderr, if a TTY is attached — so foreground ``copium proxy`` users see it
   immediately without opening a dashboard.

The "has been shown" flag is persisted in ``~/.copium/state.json`` under the
key ``first_request_shown``.  Re-runs of the proxy respect the flag and never
show the toast again.

Design constraints:
- **Zero-cost on the hot path when the flag is already set**: a plain bool
  module-level cache avoids even a file read after the first check.
- **Thread-safe**: the flag file is written under a ``threading.Lock``.
- **Never breaks a request**: every code path is wrapped in try/except.
- **Works in stateless mode**: when ``~/.copium`` is read-only, the toast
  still emits to the log but skips the file write gracefully.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("copium.proxy")

# Module-level flag — flipped to True as soon as the toast fires or we confirm
# it already fired in a previous session.  After that, _check() is a single
# bool test with no I/O.
_toast_done: bool = False
_lock = threading.Lock()

_STATE_FILE = Path.home() / ".copium" / "state.json"


def _load_state() -> dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            import json
            raw = _STATE_FILE.read_text(encoding="utf-8").strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        import json
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass  # read-only FS / stateless mode — toast still fires, just not persisted


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_usd(v: float) -> str:
    if v <= 0:
        return ""
    if v < 0.01:
        return f"~${v:.4f}"
    return f"~${v:.2f}"


def maybe_emit_toast(
    *,
    tokens_before: int,
    tokens_after: int,
    tokens_saved: int,
    savings_pct: float,
    usd_saved: float = 0.0,
    port: int = 8787,
) -> None:
    """Emit the first-request toast if it hasn't been shown before.

    Called from ``emit_request_outcome`` (effect #6) whenever
    ``tokens_saved > 0``.  Idempotent — only fires once per installation.

    Args:
        tokens_before: Original token count before compression.
        tokens_after:  Compressed token count sent upstream.
        tokens_saved:  tokens_before − tokens_after.
        savings_pct:   Compression ratio as a percentage (0-100).
        usd_saved:     Estimated cost saved (0 when litellm not available).
        port:          Proxy port, used to print the dashboard URL.
    """
    global _toast_done  # noqa: PLW0603

    if _toast_done:
        return

    with _lock:
        if _toast_done:
            return  # double-checked locking

        # ── check the persistent flag ─────────────────────────────────────
        state = _load_state()
        if state.get("first_request_shown"):
            _toast_done = True
            return

        # ── build the message ─────────────────────────────────────────────
        savings_line = (
            f"Tokens: {_fmt_tokens(tokens_before)} → {_fmt_tokens(tokens_after)}"
            f"  ({savings_pct:.1f}% saved"
        )
        if usd_saved > 0:
            savings_line += f", {_fmt_usd(usd_saved)} saved on this request"
        savings_line += ")"

        # ── log it (always visible via ``copium logs``) ───────────────────
        logger.info(
            "\U0001f389 First request compressed!  %s  "
            "View live savings: copium tui  |  Dashboard: http://localhost:%d/dashboard",
            savings_line,
            port,
        )

        # ── print to stderr when a TTY is attached ────────────────────────
        try:
            if sys.stderr.isatty():
                _print_toast(savings_line, port)
        except Exception:
            pass

        # ── persist the flag ──────────────────────────────────────────────
        state["first_request_shown"] = True
        _save_state(state)
        _toast_done = True


def _print_toast(savings_line: str, port: int) -> None:
    """Pretty-print the toast to stderr (only when attached to a TTY)."""
    try:
        import click

        click.echo(file=sys.stderr)
        click.secho("  🎉 First request compressed!", fg="green", bold=True, file=sys.stderr)
        click.secho(f"     {savings_line}", file=sys.stderr)
        click.echo(file=sys.stderr)
        click.secho("     View live savings:  copium tui", dim=True, file=sys.stderr)
        click.secho(
            f"     Or open:           http://localhost:{port}/dashboard",
            dim=True,
            file=sys.stderr,
        )
        click.echo(file=sys.stderr)
    except Exception:
        # Fallback if click isn't importable in this context
        print(
            f"\n  🎉 First request compressed!\n"
            f"     {savings_line}\n"
            f"\n"
            f"     View live savings:  copium tui\n"
            f"     Or open:           http://localhost:{port}/dashboard\n",
            file=sys.stderr,
        )


def reset_toast_state() -> None:
    """Delete the persisted first-request flag (for testing / ``copium remove``)."""
    global _toast_done  # noqa: PLW0603
    try:
        state = _load_state()
        state.pop("first_request_shown", None)
        _save_state(state)
    except Exception:
        pass
    _toast_done = False
