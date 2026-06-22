"""CLI: copium quickstart — interactive zero-config setup wizard.

Guides the user through the minimal steps needed to start compressing
LLM API requests. Detects the API key, chooses a port, starts the proxy,
and prints the one-liner export command.

Usage:
    copium quickstart
    copium quickstart --port 8787
    copium quickstart --no-start   # print instructions only
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import click

from .main import main

# Default port for quickstart (same as `copium proxy`)
_DEFAULT_PORT = 8787
_PROVIDER_MAP = {
    "ANTHROPIC_API_KEY": ("anthropic", "claude-sonnet-4-5", "ANTHROPIC_BASE_URL"),
    "OPENAI_API_KEY": ("openai", "gpt-4o", "OPENAI_BASE_URL"),
    "GEMINI_API_KEY": ("gemini", "gemini-2.0-flash", "GEMINI_BASE_URL"),
    "XAI_API_KEY": ("xai", "grok-3", "XAI_BASE_URL"),
}


def _detect_provider() -> tuple[str, str, str] | None:
    """Return (provider_name, default_model, base_url_env) or None."""
    for env_var, info in _PROVIDER_MAP.items():
        if os.environ.get(env_var):
            return info
    return None


def _port_free(port: int) -> bool:
    """Return True when the port is available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _proxy_listening(port: int) -> bool:
    """Return True when the proxy is accepting connections on the port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
        return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def _find_free_port(preferred: int) -> int:
    """Return preferred port if free, otherwise find the next free one."""
    for port in range(preferred, preferred + 20):
        if _port_free(port):
            return port
    return preferred  # fallback; proxy will error with a clear message


@main.command("quickstart")
@click.option(
    "--port",
    "-p",
    default=None,
    type=int,
    help=f"Port to start the proxy on (default: {_DEFAULT_PORT})",
)
@click.option(
    "--no-start",
    is_flag=True,
    help="Print setup instructions without starting the proxy.",
)
def quickstart(port: int | None, no_start: bool) -> None:
    """Interactive zero-config setup wizard.

    Detects your LLM provider from environment variables, starts the proxy,
    and prints the one-liner export command to point your agent at Copium.

    \b
    Examples:
        copium quickstart              # Auto-detect provider + start proxy
        copium quickstart --port 9000  # Use a custom port
        copium quickstart --no-start   # Print instructions only
    """
    click.echo()
    click.secho("  ╔═══════════════════════════════╗", fg="cyan")
    click.secho("  ║    Copium Quick Start Wizard   ║", fg="cyan", bold=True)
    click.secho("  ╚═══════════════════════════════╝", fg="cyan")
    click.echo()

    # 1. Detect provider
    provider_info = _detect_provider()
    if provider_info:
        provider_name, default_model, base_url_env = provider_info
        click.secho(f"  ✓ Provider detected: {provider_name}", fg="green")
        click.secho(f"  ✓ Default model: {default_model}", fg="green")
    else:
        click.secho(
            "  ⚠ No API key found in environment.\n"
            "  Set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, XAI_API_KEY",
            fg="yellow",
        )
        provider_name = "anthropic"
        base_url_env = "ANTHROPIC_BASE_URL"

    # 2. Choose port
    effective_port = port if port is not None else _DEFAULT_PORT
    if _proxy_listening(effective_port):
        click.secho(
            f"  ✓ Copium proxy already running on port {effective_port}", fg="green"
        )
        no_start = True  # Skip starting a duplicate
    elif not _port_free(effective_port):
        suggested = _find_free_port(effective_port + 1)
        click.secho(
            f"  ⚠ Port {effective_port} is in use — using {suggested} instead.",
            fg="yellow",
        )
        effective_port = suggested

    proxy_url = f"http://localhost:{effective_port}"
    click.echo(f"  Port: {effective_port}")
    click.echo()

    # 3. Start proxy
    if not no_start:
        click.secho("  Starting Copium proxy...", fg="cyan")
        cmd = [sys.executable, "-m", "copium.cli", "proxy", "--port", str(effective_port)]
        from copium import paths as _paths

        log_dir = _paths.log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "proxy.log"

        log_file = open(log_path, "a")  # noqa: SIM115
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            env=env,
            start_new_session=os.name == "posix",
        )

        # Wait up to 45 seconds
        for _ in range(45):
            time.sleep(1)
            if _proxy_listening(effective_port):
                break
            if proc.poll() is not None:
                log_file.close()
                click.secho(
                    f"\n  ✗ Proxy failed to start (exit code {proc.returncode}).\n"
                    f"  Check logs at: {log_path}",
                    fg="red",
                )
                sys.exit(1)
        else:
            proc.kill()
            log_file.close()
            click.secho(
                "\n  ✗ Proxy failed to start within 45 seconds.\n"
                f"  Check logs at: {log_path}",
                fg="red",
            )
            sys.exit(1)

        log_file.close()
        click.secho(f"  ✓ Proxy started on {proxy_url}", fg="green")
        click.echo(f"  Logs: {log_path}")
        click.echo()

    # 4. Print usage instructions
    click.secho("  ━━ To route your agent through Copium ━━", bold=True)
    click.echo()
    click.secho(f"  export {base_url_env}={proxy_url}", fg="yellow", bold=True)
    click.echo()
    click.secho("  Then run your agent as normal. Copium compresses in the background.", dim=True)
    click.echo()

    # 5. Show available wrap commands
    click.secho("  Or use a one-liner wrapper:", bold=True)
    wrappers = [
        ("copium wrap claude", "Claude Code (Anthropic)"),
        ("copium wrap opencode", "OpenCode"),
        ("copium wrap cursor", "Cursor"),
        ("copium wrap aider", "Aider"),
        ("copium wrap codex", "OpenAI Codex"),
    ]
    for cmd_str, desc in wrappers:
        click.echo(f"    {cmd_str:<26} # {desc}")

    click.echo()
    click.secho("  ━━ View savings ━━", bold=True)
    click.echo("    copium stats          # Quick CLI summary")
    click.echo("    copium dashboard      # Full web UI")
    click.echo()
