"""Doctor diagnostics CLI command.

Plan §6.4: `copium doctor` validates the full Copium + RTK installation.

Checks:
  - Python version and platform
  - Rust core availability
  - RTK binary installation and version
  - Supported agents installed in PATH
  - Proxy reachability and health
  - MCP retrieve tool registration (Claude)
  - CCR store
  - Telemetry status
  - Local LLM backends
  - API keys

Examples:
    copium doctor              Run all checks
    copium doctor --verbose    Show detailed output
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys

import click

from .main import main


def _check_port(port: int, timeout: float = 1.0) -> bool:
    """Return True if a local TCP port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(("127.0.0.1", port))
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def _proxy_health(port: int) -> dict | None:
    """Fetch /health from the proxy; return parsed JSON or None."""
    try:
        import httpx

        resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


@main.command()
@click.option("--port", "-p", default=8787, type=int, help="Proxy port to check (default: 8787)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def doctor(port: int, verbose: bool) -> None:
    """Diagnose Copium installation and configuration.

    \\b
    Checks:
    - Python version and platform
    - Rust core availability
    - RTK binary and version
    - Supported agents in PATH
    - Proxy health (port 8787 by default)
    - MCP retrieve tool registration
    - CCR store status
    - Telemetry status
    - Local LLM backends
    - API keys

    \\b
    Examples:
        copium doctor              Run all checks
        copium doctor --verbose    Show detailed output
        copium doctor --port 9000  Check proxy on port 9000
    """
    from copium.telemetry.beacon import is_telemetry_enabled

    click.echo()
    click.echo("  Copium Doctor")
    click.echo("  " + "=" * 50)
    click.echo()

    issues: list[str] = []
    tips: list[str] = []

    # ─── 1. Python version ──────────────────────────────────────────────────
    py_version = sys.version_info
    if py_version >= (3, 10):
        click.echo(f"  ✓ Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        click.echo(f"  ✗ Python {py_version.major}.{py_version.minor}.{py_version.micro} (requires 3.10+)")
        issues.append("Python version too old (need 3.10+)")

    # ─── 2. Platform ─────────────────────────────────────────────────────────
    system = platform.system()
    click.echo(f"  ✓ Platform: {system} ({platform.machine()})")

    # ─── 3. Copium version ───────────────────────────────────────────────────
    try:
        from copium._version import __version__
        click.echo(f"  ✓ copium-ai {__version__} installed")
    except Exception:
        click.echo("  - copium-ai: version unknown")

    # ─── 4. Rust core ────────────────────────────────────────────────────────
    try:
        from copium._core import SmartCrusher  # noqa: F401
        click.echo("  ✓ Rust core: loaded")
    except ImportError as e:
        click.echo(f"  ✗ Rust core: not available ({e})")
        issues.append("Rust core not available — run scripts/build_rust_extension.sh")

    click.echo()
    click.echo("  Checking RTK (CLI context tool)...")

    # ─── 5. RTK binary ───────────────────────────────────────────────────────
    try:
        from copium.rtk import RTK_VERSION, get_rtk_path

        rtk_path = get_rtk_path()
        if rtk_path:
            click.echo(f"  ✓ rtk {RTK_VERSION} installed at {rtk_path}")
            if verbose:
                import subprocess
                result = subprocess.run(
                    [str(rtk_path), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    click.echo(f"    rtk --version: {result.stdout.strip()}")
        else:
            click.echo("  - rtk: not installed (will be auto-downloaded on wrap)")
            tips.append("Run `copium wrap claude` to auto-install rtk")
    except Exception as e:
        click.echo(f"  - rtk: check failed ({e})")

    click.echo()
    click.echo("  Checking agent configuration...")

    # ─── 6. Agents in PATH ───────────────────────────────────────────────────
    _DETECTABLE_AGENTS = [
        ("Claude Code", "claude"),
        ("Codex", "codex"),
        ("Aider", "aider"),
        ("Cursor", "cursor"),
        ("Goose", "goose"),
        ("OpenHands", "openhands"),
    ]
    found_agents: list[str] = []
    for agent_name, binary in _DETECTABLE_AGENTS:
        path = shutil.which(binary)
        if path:
            click.echo(f"  ✓ {agent_name} detected at {path}")
            found_agents.append(agent_name)
        elif verbose:
            click.echo(f"  - {agent_name}: not found in PATH")

    if not found_agents:
        click.echo("  - No supported agents found in PATH")
        tips.append("Install an agent: claude, codex, aider, cursor, goose, or openhands")

    # ─── 7. Claude RTK hooks in settings.json ─────────────────────────────
    if shutil.which("claude"):
        import json
        from pathlib import Path

        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            try:
                payload = json.loads(settings_path.read_text(encoding="utf-8"))
                hooks = payload.get("hooks", {})
                pre_use = hooks.get("PreToolUse", [])
                rtk_registered = any(
                    any(
                        "rtk" in str(item.get("command", "")).lower()
                        for item in entry.get("hooks", [])
                        if isinstance(item, dict)
                    )
                    for entry in pre_use
                    if isinstance(entry, dict)
                )
                if rtk_registered:
                    click.echo("  ✓ RTK instructions in Claude settings.json hooks")
                else:
                    click.echo("  - RTK hook not registered in Claude settings.json")
                    tips.append("Run `copium wrap claude` to register rtk hooks")
            except Exception:
                pass

    click.echo()
    click.echo(f"  Checking proxy health (port {port})...")

    # ─── 8. Proxy reachability ───────────────────────────────────────────────
    if _check_port(port):
        health = _proxy_health(port)
        if health:
            proxy_version = health.get("copium_version", "unknown")
            click.echo(f"  ✓ Proxy responding at http://127.0.0.1:{port}/health (v{proxy_version})")
            if verbose:
                # Show transforms
                transforms = health.get("transforms_loaded", [])
                if transforms:
                    click.echo(f"    Transforms: {', '.join(transforms)}")
                # Show stats
                stats = health.get("stats", {})
                if stats:
                    tokens_saved = stats.get("tokens_saved", 0)
                    total_req = stats.get("total_requests", 0)
                    if total_req > 0:
                        click.echo(f"    Requests: {total_req}, Tokens saved: {tokens_saved:,}")
        else:
            click.echo(f"  ✓ Proxy port {port} is open but /health returned unexpected response")
    else:
        click.echo(f"  - Proxy: not running on port {port}")
        tips.append(f"Run `copium wrap claude` to start the proxy on port {port}")

    # ─── 9. MCP retrieve tool (Claude) ───────────────────────────────────────
    if shutil.which("claude"):
        import json
        from pathlib import Path

        claude_mcp_path = Path.home() / ".claude" / "claude_desktop_config.json"
        # Claude Code also stores MCP config in settings.json under "mcpServers"
        settings_path2 = Path.home() / ".claude" / "settings.json"
        mcp_found = False
        for cfg_path in (claude_mcp_path, settings_path2):
            if cfg_path.exists():
                try:
                    payload = json.loads(cfg_path.read_text(encoding="utf-8"))
                    if "copium" in str(payload.get("mcpServers", {})):
                        mcp_found = True
                        break
                except Exception:
                    pass
        if mcp_found:
            click.echo("  ✓ Copium MCP retrieve tool registered in Claude")
        else:
            click.echo("  - Copium MCP retrieve tool: not registered")
            tips.append("Run `copium wrap claude` to register the MCP retrieve tool")

    click.echo()
    click.echo("  Checking data stores...")

    # ─── 10. CCR store ────────────────────────────────────────────────────────
    try:
        from copium.cache.compression_store import get_compression_store

        store = get_compression_store()  # noqa: F841
        click.echo("  ✓ CCR store: initialized")
    except Exception as e:
        click.echo(f"  ✗ CCR store: failed ({e})")
        issues.append("CCR store initialization failed")

    # ─── 11. Telemetry ────────────────────────────────────────────────────────
    telemetry_enabled = is_telemetry_enabled()
    if telemetry_enabled:
        click.echo("  ✓ Telemetry: ENABLED (anonymous stats)")
    else:
        click.echo("  ✓ Telemetry: DISABLED (local-only)")

    click.echo()
    click.echo("  Checking optional local LLM backends...")

    # ─── 12. Local LLM backends ──────────────────────────────────────────────
    local_backends: list[str] = []
    try:
        import httpx as _httpx

        for name, url in [("Ollama", "http://localhost:11434/api/tags"), ("VLLM", "http://localhost:8000/v1/models")]:
            try:
                resp = _httpx.get(url, timeout=2)
                if resp.status_code == 200:
                    local_backends.append(name)
            except Exception:
                pass
    except ImportError:
        pass

    if local_backends:
        click.echo(f"  ✓ Local LLMs: {', '.join(local_backends)}")
    else:
        click.echo("  - Local LLMs: none detected (optional)")

    # ─── 13. API keys ──────────────────────────────────────────────────────
    api_keys: list[str] = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        api_keys.append("Anthropic")
    if os.environ.get("OPENAI_API_KEY"):
        api_keys.append("OpenAI")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        api_keys.append("Gemini")

    click.echo()
    if api_keys:
        click.echo(f"  ✓ API keys: {', '.join(api_keys)}")
    else:
        click.echo("  - API keys: none set (using local LLMs or subscription auth?)")

    # ─── Summary ────────────────────────────────────────────────────────────
    click.echo()
    click.echo("  " + "=" * 50)
    if issues:
        click.echo(f"  Found {len(issues)} issue(s):")
        for issue in issues:
            click.echo(f"    ✗ {issue}")
        click.echo()

    if tips:
        click.echo(f"  Tips ({len(tips)}):")
        for tip in tips:
            click.echo(f"    → {tip}")
        click.echo()

    if not issues:
        click.echo("  ✓ All checks passed!")
        click.echo()
        click.echo("  Run `copium wrap claude` to start a session.")
    else:
        click.echo("  Fix the issues above and re-run `copium doctor`.")

    click.echo()
