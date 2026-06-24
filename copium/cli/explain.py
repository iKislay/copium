"""CLI: `copium explain <request-id>` — Transparency Layer §8a.

Shows exactly what Copium did to a specific proxied request:

  $ copium explain hr_1719162271_000042

  Request hr_1719162271_000042 — POST /v1/messages — 12:04:31
  ─────────────────────────────────────────────────────────────

  Input
    Original:    4,812 tokens
    Compressed:    892 tokens  (81.5% saved, ~$0.01 estimated)

  Transforms applied
    1. SmartCrusher   → 4,812 → 892 tokens  (-81.5%)
    2. CacheAligner   → moved session_id to suffix

  Overhead: 48 ms

  Quality guard
    ✓ No inflation detected (892 < 4812)
    ✓ Cached: No (first-pass compression)

  Inspect the audit log:
    tail -f ~/.copium/logs/audit.jsonl | jq .

Works both when the proxy is running (queries /audit/<id>) and offline
(reads directly from ~/.copium/logs/audit.jsonl).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click

from .main import main


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_entry_offline(request_id: str) -> dict | None:
    """Read from local audit.jsonl — works even when proxy is offline.

    Uses ``find_by_id`` for O(1) early-return instead of reading the entire
    file into memory.
    """
    try:
        from copium.proxy.audit_writer import find_by_id
        return find_by_id(request_id)
    except Exception:
        pass
    # Fallback: raw path read without importing audit_writer
    try:
        from copium.proxy.audit_writer import get_audit_path
        log_path = get_audit_path()
    except Exception:
        log_path = Path.home() / ".copium" / "logs" / "audit.jsonl"
    if not log_path.exists():
        return None
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
                if obj.get("req") == request_id:
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def _load_entry_from_proxy(request_id: str, port: int) -> dict | None:
    """Hit the proxy /audit/<id> endpoint."""
    try:
        import httpx
        r = httpx.get(f"http://127.0.0.1:{port}/audit/{request_id}", timeout=2.0)
        if r.status_code == 200:
            return r.json().get("entry")
    except Exception:
        pass
    return None


def _load_detailed_log(request_id: str, port: int) -> dict | None:
    """Get the full request log entry (with transforms detail) from /stats."""
    try:
        import httpx
        # The in-memory request logger has more detail than audit.jsonl
        r = httpx.get(f"http://127.0.0.1:{port}/stats", timeout=2.0)
        if r.status_code == 200:
            logs = r.json().get("recent_requests", [])
            for log in logs:
                if log.get("request_id") == request_id:
                    return log
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Rich formatter
# ---------------------------------------------------------------------------

def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n:,}"
    return str(n)


def _rough_usd(tokens_saved: int, model: str) -> str:
    """Rough cost estimate — pulls from provider pricing when available.

    Falls back to hardcoded estimates when provider modules are unavailable.
    Rates last verified: 2026-06-24.
    """
    rate = _estimate_rate(model)
    usd = tokens_saved * rate
    if usd < 0.0001:
        return f"~${usd:.5f}"
    if usd < 0.01:
        return f"~${usd:.4f}"
    return f"~${usd:.3f}"


def _estimate_rate(model: str) -> float:
    """Return per-token cost rate (USD) for a model, trying provider modules first."""
    model_l = model.lower()

    # Try Anthropic provider pricing (most comprehensive)
    try:
        from copium.providers.anthropic import ANTHROPIC_PRICING, _PATTERN_DEFAULTS
        # Exact match first
        if model_l in ANTHROPIC_PRICING:
            return ANTHROPIC_PRICING[model_l]["input"] / 1_000_000
        # Pattern match (opus/sonnet/haiku)
        for pattern, info in _PATTERN_DEFAULTS.items():
            if pattern in model_l:
                return info["pricing"]["input"] / 1_000_000
    except Exception:
        pass

    # Try OpenAI provider pricing
    try:
        from copium.providers.openai import _PRICING
        for prefix, pricing in _PRICING.items():
            if model_l.startswith(prefix):
                return pricing[0] / 1_000_000  # input price
    except Exception:
        pass

    # Hardcoded fallbacks (rates last verified: 2026-06-24)
    if "opus" in model_l:
        return 15.0 / 1_000_000
    if "sonnet" in model_l:
        return 3.0 / 1_000_000
    if "haiku" in model_l:
        return 0.25 / 1_000_000
    if "gpt-4" in model_l:
        return 10.0 / 1_000_000
    if "gpt-3" in model_l:
        return 0.5 / 1_000_000
    return 3.0 / 1_000_000  # blended default


def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts


def _render_explain(entry: dict, detail: dict | None) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    console = Console()

    req_id = entry.get("req", "?")
    ts = _fmt_ts(entry.get("ts", ""))
    req_path = entry.get("path", "/v1/messages")
    model = entry.get("model", "?")
    provider = entry.get("provider", "?")
    tokens_in = int(entry.get("tokens_in", 0))
    tokens_out = int(entry.get("tokens_out", tokens_in))
    tokens_saved = max(0, tokens_in - tokens_out)
    savings_frac = entry.get("savings", 0.0)
    savings_pct = round(savings_frac * 100, 1)
    overhead_ms = entry.get("overhead_ms", 0)
    cached = entry.get("cached", False)
    transforms = entry.get("transforms", [])

    # Prefer detail log transforms (they have more info)
    if detail and detail.get("transforms_applied"):
        transforms = detail["transforms_applied"]

    # ── Header ──────────────────────────────────────────────────────────
    console.print()
    console.print(
        f"[bold cyan]Request[/bold cyan] [bold]{req_id}[/bold]"
        f"  [dim]{req_path}[/dim]"
        f"  [dim]{ts}[/dim]"
        f"  [dim]{provider}/{model}[/dim]"
    )
    console.print(Rule(style="dim"))

    # ── Input section ────────────────────────────────────────────────────
    console.print("\n[bold]Input[/bold]")
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", min_width=14)
    t.add_column()
    t.add_row("Original:", f"[white]{_fmt_tokens(tokens_in)} tokens[/white]")
    if tokens_saved > 0:
        est_usd = _rough_usd(tokens_saved, model)
        t.add_row(
            "Compressed:",
            f"[bold green]{_fmt_tokens(tokens_out)} tokens[/bold green]"
            f"  [dim]({savings_pct}% saved, {est_usd} estimated)[/dim]",
        )
    else:
        t.add_row("Compressed:", f"[dim]{_fmt_tokens(tokens_out)} tokens (passthrough)[/dim]")
    console.print(t)

    # ── Transforms section ───────────────────────────────────────────────
    console.print("\n[bold]Transforms applied[/bold]")
    if transforms:
        for i, xform in enumerate(transforms, 1):
            # Try to decode structured info if present
            console.print(f"  [cyan]{i}.[/cyan] [bold]{xform}[/bold]")
    else:
        console.print("  [dim](none — passthrough)[/dim]")

    # ── Overhead ─────────────────────────────────────────────────────────
    console.print(f"\n  [dim]Overhead: {overhead_ms:.0f} ms[/dim]")

    # ── Quality guard ────────────────────────────────────────────────────
    console.print("\n[bold]Quality guard[/bold]")
    if tokens_out <= tokens_in:
        console.print(
            f"  [green]✓[/green] No inflation detected "
            f"[dim]({_fmt_tokens(tokens_out)} ≤ {_fmt_tokens(tokens_in)})[/dim]"
        )
    else:
        console.print(
            f"  [red]✗[/red] Inflation detected — passthrough used "
            f"[dim]({_fmt_tokens(tokens_out)} > {_fmt_tokens(tokens_in)})[/dim]"
        )
    if cached:
        console.print("  [green]✓[/green] Served from Copium response cache")
    else:
        console.print("  [dim]○ Cached: No (live request to upstream)[/dim]")

    # ── Audit log hint ───────────────────────────────────────────────────
    try:
        from copium.proxy.audit_writer import get_audit_path
        log_path = get_audit_path()
    except Exception:
        log_path = Path.home() / ".copium" / "logs" / "audit.jsonl"
    console.print(f"\n[dim]Inspect the full audit log:[/dim]")
    console.print(f"  [dim]tail -f {log_path} | jq .[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@main.command("explain")
@click.argument("request_id")
@click.option(
    "--port", "-p", default=8787, type=int, envvar="COPIUM_PORT", show_default=True,
    help="Proxy port to query for live detail.",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON entry.")
def explain(request_id: str, port: int, as_json: bool) -> None:
    """Show what Copium did to a specific proxied request (§8a).

    \b
    REQUEST_ID is the short ID shown in `copium tui` live feed or in the
    X-Copium-Request-Id response header.

    \b
    Examples:
        copium explain hr_1719162271_000042
        copium explain hr_1719162271_000042 --json
        curl -si http://localhost:8787/v1/messages ... | grep x-copium-request-id
    """
    # Try live proxy first (has richer detail)
    entry = _load_entry_from_proxy(request_id, port)
    detail = None
    if entry:
        detail = _load_detailed_log(request_id, port)
    else:
        entry = _load_entry_offline(request_id)

    if entry is None:
        raise click.ClickException(
            f"Request {request_id!r} not found.\n"
            f"  • Is the request ID correct? (check `copium tui` or X-Copium-Request-Id header)\n"
            f"  • Was it from a recent session? (older entries may have been rotated)\n"
            f"  • Try: copium tui --snapshot  to see recent request IDs."
        )

    if as_json:
        click.echo(json.dumps(entry, indent=2, default=str))
        return

    _render_explain(entry, detail)
