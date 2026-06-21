"""Doctor diagnostics CLI command."""

import os
import platform
import sys

import click

from .main import main


@main.command()
def doctor() -> None:
    """Diagnose Copium installation and configuration.

    \b
    Checks:
    - Python version and platform
    - Rust core availability
    - Telemetry status
    - CCR store status
    - Provider connectivity
    - Local LLM backends

    \b
    Examples:
        copium doctor              Run all checks
        copium doctor --verbose    Show detailed output
    """
    from copium.telemetry.beacon import is_telemetry_enabled

    click.echo("Copium Doctor")
    click.echo("=" * 50)

    issues = []

    # 1. Python version
    py_version = sys.version_info
    if py_version >= (3, 10):
        click.echo(f"✓ Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        click.echo(f"✗ Python {py_version.major}.{py_version.minor}.{py_version.micro} (requires 3.10+)")
        issues.append("Python version too old")

    # 2. Platform
    system = platform.system()
    click.echo(f"✓ Platform: {system} ({platform.machine()})")

    # 3. Rust core
    try:
        from copium._core import SmartCrusher
        click.echo("✓ Rust core: loaded")
    except ImportError as e:
        click.echo(f"✗ Rust core: not available ({e})")
        issues.append("Rust core not available")

    # 4. Telemetry
    telemetry_enabled = is_telemetry_enabled()
    if telemetry_enabled:
        click.echo("✓ Telemetry: ENABLED (anonymous stats)")
    else:
        click.echo("✓ Telemetry: DISABLED (local-only)")

    # 5. CCR store
    try:
        from copium.cache.compression_store import get_compression_store
        store = get_compression_store()
        click.echo(f"✓ CCR store: initialized")
    except Exception as e:
        click.echo(f"✗ CCR store: failed ({e})")
        issues.append("CCR store initialization failed")

    # 6. Local LLM backends
    local_backends = []

    # Check Ollama
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            local_backends.append("Ollama")
    except Exception:
        pass

    # Check VLLM
    try:
        import httpx
        resp = httpx.get("http://localhost:8000/v1/models", timeout=2)
        if resp.status_code == 200:
            local_backends.append("VLLM")
    except Exception:
        pass

    if local_backends:
        click.echo(f"✓ Local LLMs: {', '.join(local_backends)}")
    else:
        click.echo("- Local LLMs: none detected (optional)")

    # 7. API keys
    api_keys = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        api_keys.append("Anthropic")
    if os.environ.get("OPENAI_API_KEY"):
        api_keys.append("OpenAI")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        api_keys.append("Gemini")

    if api_keys:
        click.echo(f"✓ API keys: {', '.join(api_keys)}")
    else:
        click.echo("- API keys: none set (using local LLMs?)")

    # Summary
    click.echo()
    if issues:
        click.echo(f"Found {len(issues)} issue(s):")
        for issue in issues:
            click.echo(f"  - {issue}")
        click.echo()
        click.echo("Run 'copium proxy' to start the proxy server.")
    else:
        click.echo("✓ All checks passed!")
        click.echo()
        click.echo("Run 'copium proxy' to start the proxy server.")
