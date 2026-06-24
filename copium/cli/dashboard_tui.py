"""CLI: live TUI dashboard showing compression savings in real-time.

Plan §7 — Terminal UI (TUI) Dashboard.

Uses rich.live + rich.layout to deliver a proper split-pane terminal UI:

┌─ Copium ──────────────────────────────────── v0.x.x  ● Running ─┐
│ SESSION ──────────────────  ALL TIME ──────────────────────────── │
│ Agent:    Claude Code       Tokens saved:   1.4B                   │
│ Duration: 1h 42m            Sessions:       50,412                 │
│ Tokens in:284,312           Avg:            38%                    │
│ Saved:    141,203 (49.7%)   Est. saved:     $4,218                 │
│                                                                    │
│ TRANSFORMS ───────────────────────────────────────────────────── │
│ SmartCrusher  ████████████████░░░░  82%  12 hits                  │
│ ...                                                                │
│                                                                    │
│ LIVE REQUESTS ────────────────────────────────────────────────── │
│ 12:04:31  POST /v1/messages  in:4812 out:892  saved:81.5%         │
│ ...                                                                │
│ [q] quit  [p] pause  [r] reset  [?] help                          │
└────────────────────────────────────────────────────────────────────┘

Key features:
- Real-time updates (2s data poll, display refresh on every iteration)
- Per-transform breakdown with rich bar charts
- Live request stream polled from proxy /audit endpoint (or stub feed)
- Keyboard shortcuts: q quit, p pause, r reset view, ? help
- Falls back to a clean "no data" state when proxy is not running
- `copium tui` and `copium dashboard` both invoke it
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from .main import main

# ---------------------------------------------------------------------------
# Version helper
# ---------------------------------------------------------------------------

def _version() -> str:
    try:
        from importlib.metadata import version
        return version("copium-ai")
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# Data layer  (polls SavingsTracker + proxy /audit endpoint)
# ---------------------------------------------------------------------------

_LIVE_FEED: deque[dict] = deque(maxlen=200)
_FEED_LOCK = threading.Lock()

# Transform shortname lookup
_XFORM_LABELS = {
    "smart_crusher": "SmartCrusher",
    "smartcrusher": "SmartCrusher",
    "session_dedup": "Session Dedup",
    "toon_encoder": "TOON Encoder",
    "toon": "TOON Encoder",
    "error_compressor": "Error Compress.",
    "cache_aligner": "Cache Aligner",
    "diff_response": "Diff Response",
    "output_compressor": "Output Compres.",
    "code_compressor": "Code Compres.",
    "pager": "Pager",
    "image_compressor": "Image Compres.",
}


def _shorten_transform(name: str) -> str:
    low = name.lower().replace("-", "_")
    for k, v in _XFORM_LABELS.items():
        if k in low:
            return v
    # Capitalize first segment
    parts = name.replace("_", " ").replace("-", " ").split()
    return " ".join(p.capitalize() for p in parts)[:20]


def _load_savings() -> dict[str, Any]:
    """Load stats from SavingsTracker (works even when proxy is offline)."""
    try:
        from copium.proxy.savings_tracker import SavingsTracker
        tracker = SavingsTracker()
        return tracker.stats_preview()
    except Exception:
        return {}


def _probe_proxy(port: int) -> dict[str, Any] | None:
    """Try to hit the proxy /health endpoint; return JSON or None."""
    try:
        import httpx
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _poll_audit(port: int, since_id: str | None) -> list[dict]:
    """Poll proxy /audit endpoint for new request entries."""
    try:
        import httpx
        params: dict[str, Any] = {"limit": 20}
        if since_id:
            params["since"] = since_id
        r = httpx.get(f"http://127.0.0.1:{port}/audit", params=params, timeout=1.0)
        if r.status_code == 200:
            return r.json().get("entries", [])
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_usd(v: float) -> str:
    if v == 0:
        return "$0.00"
    if v < 0.01:
        return f"${v:.4f}"
    if v < 1:
        return f"${v:.3f}"
    return f"${v:,.2f}"


def _fmt_duration(started_at: str | None) -> str:
    """Return human-readable elapsed time since started_at ISO string."""
    if not started_at:
        return "--"
    try:
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
        if elapsed < 0:
            return "--"
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"
    except Exception:
        return "--"


def _bar(value: float, width: int = 18) -> str:
    """Return a block-character bar 0–width filled to value (0.0–1.0)."""
    filled = max(0, min(width, round(value * width)))
    return "█" * filled + "░" * (width - filled)


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Rich layout builders
# ---------------------------------------------------------------------------

def _make_header(running: bool, port: int) -> "rich.panel.Panel":  # noqa: F821
    from rich.text import Text
    from rich.panel import Panel

    ver = _version()
    status_icon = "[bold green]● Running[/bold green]" if running else "[red]○ Stopped[/red]"
    hint = f"port {port}" if running else "run: copium start"
    title = Text.from_markup(
        f"[bold cyan]Copium[/bold cyan]  [dim]v{ver}[/dim]"
        f"  {status_icon}  [dim]({hint})[/dim]"
    )
    return Panel(title, padding=(0, 1), border_style="cyan")


def _make_stats_panel(data: dict) -> "rich.panel.Panel":  # noqa: F821
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns

    session = data.get("display_session", {})
    lifetime = data.get("lifetime", {})

    # ── session ─────────────────────────────────────────────────────────
    st = Table.grid(padding=(0, 2))
    st.add_column(style="dim", min_width=13)
    st.add_column(style="bold")

    reqs = session.get("requests", 0)
    tok_saved = session.get("tokens_saved", 0)
    tok_in = session.get("total_input_tokens", 0)
    pct = session.get("savings_percent", 0.0)
    usd = session.get("compression_savings_usd", 0.0)
    started = session.get("started_at")
    duration = _fmt_duration(started)

    st.add_row("Requests", f"[green]{reqs:,}[/green]")
    st.add_row("Duration", f"[cyan]{duration}[/cyan]")
    st.add_row("Tokens in", f"[white]{_fmt_tokens(tok_in)}[/white]")
    st.add_row(
        "Saved",
        f"[bold green]{_fmt_tokens(tok_saved)}[/bold green]"
        + (f" [dim]({pct:.1f}%)[/dim]" if pct > 0 else ""),
    )
    st.add_row("Cost saved", f"[bold yellow]{_fmt_usd(usd)}[/bold yellow]")

    # ── lifetime ────────────────────────────────────────────────────────
    lt = Table.grid(padding=(0, 2))
    lt.add_column(style="dim", min_width=15)
    lt.add_column(style="bold")

    lt_tok = lifetime.get("tokens_saved", 0)
    lt_reqs = lifetime.get("requests", 0)
    lt_usd = lifetime.get("compression_savings_usd", 0.0)
    lt_in = lifetime.get("total_input_tokens", 0)
    lt_pct = (lt_tok / (lt_tok + lt_in) * 100) if (lt_tok + lt_in) > 0 else 0.0

    lt.add_row("Tokens saved", f"[bold green]{_fmt_tokens(lt_tok)}[/bold green]")
    lt.add_row("Requests", f"[green]{lt_reqs:,}[/green]")
    lt.add_row("Avg savings", f"[cyan]{lt_pct:.1f}%[/cyan]")
    lt.add_row("Est. saved", f"[bold yellow]{_fmt_usd(lt_usd)}[/bold yellow]")

    cols = Columns(
        [
            Panel(st, title="[bold]SESSION[/bold]", border_style="green", padding=(0, 1)),
            Panel(lt, title="[bold]ALL TIME[/bold]", border_style="blue", padding=(0, 1)),
        ],
        expand=True,
    )
    return Panel(cols, border_style="dim", padding=(0, 0))


def _make_transforms_panel(data: dict) -> "rich.panel.Panel":  # noqa: F821
    """Build the per-transform bar chart panel from recent_history stats."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text

    # We don't have per-transform stats in SavingsTracker — build a synthetic
    # breakdown from the recent_history timestamps and savings deltas,
    # or read from the SQLite metrics.db if available.
    transforms = _load_transform_stats()

    t = Table.grid(padding=(0, 1))
    t.add_column(min_width=16, style="cyan")   # name
    t.add_column(min_width=20)                  # bar
    t.add_column(min_width=5, justify="right")  # pct
    t.add_column(min_width=8, justify="right", style="green")  # saved
    t.add_column(min_width=6, justify="right", style="dim")    # hits

    if not transforms:
        t.add_row(
            "[dim]No transform data yet[/dim]", "", "", "", ""
        )
    else:
        max_saved = max((x["saved"] for x in transforms), default=1) or 1
        for x in transforms[:8]:
            saved = x["saved"]
            pct = (saved / max_saved) if max_saved > 0 else 0.0
            bar_str = _bar(pct, 18)
            pct_label = f"{pct * 100:.0f}%"
            t.add_row(
                _shorten_transform(x["name"]),
                f"[green]{bar_str}[/green]",
                f"[dim]{pct_label}[/dim]",
                _fmt_tokens(saved),
                f"{x['hits']}x",
            )

    return Panel(t, title="[bold]TRANSFORMS[/bold]", border_style="magenta", padding=(0, 1))


def _make_feed_panel(max_rows: int = 8) -> "rich.panel.Panel":  # noqa: F821
    """Build the live request stream panel."""
    from rich.table import Table
    from rich.panel import Panel

    t = Table.grid(padding=(0, 1))
    t.add_column(min_width=8, style="dim")    # timestamp
    t.add_column(min_width=6, style="dim")    # method/path
    t.add_column(min_width=7, justify="right") # in
    t.add_column(min_width=7, justify="right") # out
    t.add_column(min_width=8, justify="right") # saved%
    t.add_column(min_width=6, justify="right", style="dim")  # latency
    t.add_column(style="dim")                  # transform tag

    with _FEED_LOCK:
        entries = list(_LIVE_FEED)[-max_rows:]

    if not entries:
        t.add_row(
            "[dim]──[/dim]",
            "[dim]Waiting for requests…[/dim]",
            "", "", "", "", ""
        )
    else:
        for e in reversed(entries):
            tokens_in = e.get("tokens_in", 0)
            tokens_out = e.get("tokens_out", 0)
            saved_pct = e.get("saved_pct", 0.0)
            latency = e.get("latency_ms", 0)
            ts = e.get("ts", "")
            xform = e.get("transform", "")[:12]
            # Colour saved% by magnitude
            if saved_pct >= 60:
                pct_style = "bold green"
            elif saved_pct >= 20:
                pct_style = "green"
            elif saved_pct > 0:
                pct_style = "yellow"
            else:
                pct_style = "dim"

            t.add_row(
                ts,
                "POST /v1",
                f"[white]{_fmt_tokens(tokens_in)}[/white]",
                f"[dim]{_fmt_tokens(tokens_out)}[/dim]",
                f"[{pct_style}]{saved_pct:.1f}%[/{pct_style}]",
                f"{latency:.0f}ms",
                f"[dim]{xform}[/dim]",
            )

    return Panel(
        t,
        title="[bold]LIVE REQUESTS[/bold]",
        border_style="yellow",
        padding=(0, 1),
        subtitle="[dim]newest first[/dim]",
    )


def _make_footer(paused: bool) -> "rich.text.Text":  # noqa: F821
    from rich.text import Text

    if paused:
        return Text.from_markup(
            "[bold yellow]  ⏸  PAUSED  [/bold yellow]"
            "  [dim][p] resume  [q] quit[/dim]"
        )
    return Text.from_markup(
        "  [dim][q] quit  [p] pause  [r] reset session view  [?] help[/dim]"
    )


def _make_help_panel() -> "rich.panel.Panel":  # noqa: F821
    from rich.table import Table
    from rich.panel import Panel

    t = Table.grid(padding=(0, 3))
    t.add_column(style="bold cyan", min_width=6)
    t.add_column()
    t.add_row("q", "Quit the TUI")
    t.add_row("p", "Pause / resume live updates")
    t.add_row("r", "Reset the session view (scroll to top)")
    t.add_row("?", "Toggle this help panel")
    t.add_row("Ctrl-C", "Force quit")
    return Panel(t, title="[bold]Keyboard Shortcuts[/bold]", border_style="cyan")


# ---------------------------------------------------------------------------
# Transform stats helper — tries SQLite first, falls back to nothing
# ---------------------------------------------------------------------------

def _load_transform_stats() -> list[dict]:
    """Load per-transform stats from the SQLite metrics DB, if it exists."""
    try:
        from copium.paths import workspace_dir
        db_path = workspace_dir() / "metrics.db"
        if not db_path.exists():
            return []
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT transform,
                   COUNT(*) AS hits,
                   SUM(COALESCE(tokens_before - tokens_after, 0)) AS saved
            FROM transform_applied
            WHERE timestamp > datetime('now', '-1 hour')
            GROUP BY transform
            ORDER BY saved DESC
            LIMIT 10
            """
        ).fetchall()
        conn.close()
        return [{"name": r["transform"], "hits": r["hits"], "saved": r["saved"] or 0} for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Keyboard input (non-blocking, raw mode on Unix)
# ---------------------------------------------------------------------------

def _setup_raw_stdin() -> bool:
    """Put stdin in raw mode so we can read single keystrokes. Returns True on success."""
    if not sys.stdin.isatty():
        return False
    try:
        import tty, termios  # noqa: F401
        tty.setraw(sys.stdin.fileno())
        return True
    except Exception:
        return False


def _restore_stdin(old_settings: Any) -> None:
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
    except Exception:
        pass


def _read_key_nonblock() -> str | None:
    """Return a single keypress char or None if nothing is waiting."""
    try:
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            return ch
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Background data poller thread
# ---------------------------------------------------------------------------

class _DataPoller:
    """Runs in a background thread, continuously refreshing stats from disk/proxy."""

    def __init__(self, port: int, poll_interval: float = 2.0) -> None:
        self._port = port
        self._interval = poll_interval
        self._running = True
        self._data: dict = {}
        self._running_flag = False  # proxy running?
        self._health: dict = {}
        self._last_audit_id: str | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self._running:
            try:
                data = _load_savings()
                health = _probe_proxy(self._port)
                running = health is not None

                # Poll live feed from /audit
                if running:
                    new_entries = _poll_audit(self._port, self._last_audit_id)
                    if new_entries:
                        with _FEED_LOCK:
                            for e in new_entries:
                                _LIVE_FEED.append(self._normalize_audit_entry(e))
                        self._last_audit_id = new_entries[-1].get("id")

                with self._lock:
                    self._data = data
                    self._health = health or {}
                    self._running_flag = running
            except Exception:
                pass
            time.sleep(self._interval)

    @staticmethod
    def _normalize_audit_entry(e: dict) -> dict:
        """Normalize a raw /audit entry to our internal feed format."""
        tokens_in = e.get("input_tokens_original", e.get("tokens_before", 0))
        tokens_out = e.get("input_tokens_optimized", e.get("tokens_after", tokens_in))
        saved = max(0, tokens_in - tokens_out)
        saved_pct = (saved / tokens_in * 100) if tokens_in > 0 else 0.0
        transforms = e.get("transforms_applied", [])
        xform = _shorten_transform(transforms[0]) if transforms else "Passthru"
        return {
            "ts": _now_ts(),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "saved_pct": saved_pct,
            "latency_ms": e.get("optimization_latency_ms", e.get("latency_ms", 0)),
            "transform": xform,
            "id": e.get("request_id", ""),
        }

    def get(self) -> tuple[dict, bool, dict]:
        """Return (savings_data, is_running, health_data)."""
        with self._lock:
            return self._data.copy(), self._running_flag, self._health.copy()

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Main TUI loop
# ---------------------------------------------------------------------------

def _run_tui(port: int = 8787, refresh_rate: float = 0.5) -> None:
    """Run the live TUI dashboard. Blocks until the user presses q."""
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.console import Console

    console = Console()

    # Save terminal state for raw-mode keyboard
    old_settings: Any = None
    raw_ok = False
    if sys.stdin.isatty():
        try:
            import termios
            old_settings = termios.tcgetattr(sys.stdin.fileno())
        except Exception:
            pass
        raw_ok = _setup_raw_stdin()

    paused = False
    show_help = False
    poller = _DataPoller(port=port, poll_interval=2.0)

    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=1),
    )
    layout["body"].split_column(
        Layout(name="stats", size=9),
        Layout(name="transforms", size=12),
        Layout(name="feed"),
    )

    def _refresh(data: dict, running: bool) -> None:
        layout["header"].update(_make_header(running, port))
        if show_help:
            layout["body"].update(_make_help_panel())
        else:
            layout["stats"].update(_make_stats_panel(data))
            layout["transforms"].update(_make_transforms_panel(data))
            layout["feed"].update(_make_feed_panel(max_rows=8))
        layout["footer"].update(_make_footer(paused))

    # Initial render with whatever we have
    data, running, _ = poller.get()
    _refresh(data, running)

    try:
        with Live(
            layout,
            console=console,
            screen=True,
            refresh_per_second=int(1 / refresh_rate),
            transient=False,
        ) as live:
            while True:
                # ── keyboard ───────────────────────────────────────────
                ch = _read_key_nonblock() if raw_ok else None
                if ch:
                    if ch in ("q", "Q", "\x03"):  # q or Ctrl-C
                        break
                    elif ch in ("p", "P"):
                        paused = not paused
                    elif ch in ("r", "R"):
                        with _FEED_LOCK:
                            _LIVE_FEED.clear()
                    elif ch in ("?", "h", "H"):
                        show_help = not show_help

                # ── data + render ──────────────────────────────────────
                if not paused:
                    data, running, _ = poller.get()
                    _refresh(data, running)

                time.sleep(refresh_rate)
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()
        if raw_ok and old_settings is not None:
            _restore_stdin(old_settings)


# ---------------------------------------------------------------------------
# Fallback: non-live snapshot mode (for terminals with no TTY)
# ---------------------------------------------------------------------------

def _render_snapshot(port: int) -> None:
    """Render a one-shot snapshot without Live mode."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.columns import Columns

    console = Console()
    data = _load_savings()
    running = _probe_proxy(port) is not None

    console.print(_make_header(running, port))
    console.print(_make_stats_panel(data))
    console.print(_make_transforms_panel(data))
    console.print(_make_feed_panel())
    console.print(
        "[dim]Run [bold]copium tui[/bold] in an interactive terminal for live updates.[/dim]"
    )


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------

@main.group("tui", invoke_without_command=True)
@click.option(
    "--port", "-p", default=8787, type=int, envvar="COPIUM_PORT", show_default=True,
    help="Port the Copium proxy is running on.",
)
@click.option(
    "--snapshot", is_flag=True,
    help="Print a one-shot stats snapshot instead of the live dashboard.",
)
@click.option(
    "--json", "as_json", is_flag=True,
    help="Print stats as JSON and exit.",
)
@click.pass_context
def tui(ctx: click.Context, port: int, snapshot: bool, as_json: bool) -> None:
    """Terminal UI dashboard for live compression stats.

    \b
    Shows session and all-time savings, per-transform bar charts,
    and a live stream of proxied requests.

    \b
    Keyboard shortcuts:
        q       Quit
        p       Pause / resume
        r       Reset session view
        ?       Toggle help panel

    \b
    Examples:
        copium tui                  Open the live TUI dashboard
        copium tui --snapshot       One-shot snapshot (non-interactive)
        copium tui --json           Print stats as JSON
    """
    if ctx.invoked_subcommand is not None:
        return

    if as_json:
        data = _load_savings()
        click.echo(json.dumps(data, indent=2, default=str))
        return

    if snapshot or not sys.stdout.isatty():
        _render_snapshot(port)
        return

    _run_tui(port=port)


# ── `copium tui snapshot` subcommand ──────────────────────────────────────

@tui.command("snapshot")
@click.option("--port", "-p", default=8787, type=int, envvar="COPIUM_PORT", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def tui_snapshot(port: int, as_json: bool) -> None:
    """Print a one-shot stats snapshot."""
    if as_json:
        data = _load_savings()
        click.echo(json.dumps(data, indent=2, default=str))
        return
    _render_snapshot(port)


# ---------------------------------------------------------------------------
# `copium dashboard` — top-level alias for backwards compatibility
# ---------------------------------------------------------------------------

@main.command("dashboard")
@click.option(
    "--port", "-p", default=8787, type=int, envvar="COPIUM_PORT", show_default=True,
    help="Port the Copium proxy is running on.",
)
@click.option("--watch", "-w", is_flag=True, help="Alias for the live TUI mode.")
@click.option("--json-output", is_flag=True, help="Output stats as JSON.")
def dashboard(port: int, watch: bool, json_output: bool) -> None:
    """Live terminal dashboard showing compression savings.

    \b
    Examples:
        copium dashboard          One-shot stats snapshot
        copium dashboard -w       Full live TUI (same as `copium tui`)
        copium dashboard --json   Output as JSON
    """
    if json_output:
        data = _load_savings()
        click.echo(json.dumps(data, indent=2, default=str))
        return

    if watch or sys.stdout.isatty():
        _run_tui(port=port)
    else:
        _render_snapshot(port)
