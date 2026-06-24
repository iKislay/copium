"""Durable agent initialization commands."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from hashlib import sha1
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

import click

from copium.install.models import ConfigScope, InstallPreset, RuntimeKind, SupervisorKind
from copium.install.paths import claude_settings_path, codex_config_path, validate_profile_name
from copium.install.planner import build_manifest
from copium.install.providers import _apply_unix_env_scope, _apply_windows_env_scope
from copium.install.runtime import (
    acquire_runtime_start_lock,
    resolve_copium_command,
    runtime_status,
    start_detached_agent,
    start_persistent_docker,
    stop_runtime,
    wait_ready,
)
from copium.install.state import load_manifest, save_manifest
from copium.install.supervisors import start_supervisor
from copium.providers.claude import TOOL_SEARCH_DEFAULT, TOOL_SEARCH_ENV
from copium.providers.codex.install import codex_uses_chatgpt_auth

from .main import main

logger = logging.getLogger(__name__)

_VERBOSE_HANDLER_ATTR = "_copium_init_verbose_handler"

_GLOBAL_PROFILE = "init-user"
_CLAUDE_HOOK_MARKER = "copium-init-claude"
_COPILOT_HOOK_MARKER = "copium-init-copilot"
_CODEX_HOOK_MARKER = "copium-init-codex"
_CODEX_PROVIDER_MARKER_START = "# --- Copium init provider ---"
_CODEX_PROVIDER_MARKER_END = "# --- end Copium init provider ---"
_CODEX_FEATURE_MARKER_START = "# --- Copium init features ---"
_CODEX_FEATURE_MARKER_END = "# --- end Copium init features ---"
_SUPPORTED_TARGETS = ("claude", "copilot", "codex", "openclaw", "cursor", "aider")
_LOCAL_TARGETS = {"claude", "codex", "cursor", "aider"}
_GLOBAL_TARGETS = {"claude", "copilot", "codex", "openclaw", "cursor", "aider"}
_STARTUP_READY_TIMEOUT_SECONDS = 15

# Shell rc file markers for copium env vars (plan §3a)
_COPIUM_ENV_MARKER_START = "# >>> copium start <<<"
_COPIUM_ENV_MARKER_END = "# <<< copium end <<<"
_COPIUM_ENV_PATTERN = re.compile(
    re.escape(_COPIUM_ENV_MARKER_START) + r".*?" + re.escape(_COPIUM_ENV_MARKER_END),
    re.DOTALL,
)

# Global config path
_GLOBAL_CONFIG_DIR = Path.home() / ".copium"
_GLOBAL_CONFIG_PATH = _GLOBAL_CONFIG_DIR / "config.toml"
_TOML_TABLE_HEADER_RE = re.compile(r"^[ \t]*(?:\[\[[^\]\r\n]+\]\]|\[[^\]\r\n]+\])[ \t]*(?:#.*)?$")
_TOML_FEATURES_NAME_RE = r"(?:features|\"features\"|'features')"
_TOML_CODEX_HOOKS_NAME_RE = r"(?:codex_hooks|\"codex_hooks\"|'codex_hooks')"
_CODEX_FEATURES_TABLE_RE = re.compile(
    rf"^[ \t]*\[[ \t]*{_TOML_FEATURES_NAME_RE}[ \t]*\][ \t]*(?:#.*)?$"
)
_CODEX_FEATURES_DOTTED_LEGACY_RE = re.compile(
    rf"^[ \t]*{_TOML_FEATURES_NAME_RE}[ \t]*\.[ \t]*{_TOML_CODEX_HOOKS_NAME_RE}[ \t]*="
)
_CODEX_FEATURES_LEGACY_KEY_RE = re.compile(rf"^[ \t]*{_TOML_CODEX_HOOKS_NAME_RE}[ \t]*=")


def _get_user_shell_rc_files() -> list[Path]:
    """Return shell rc files that exist and can be patched with copium env vars."""
    home = Path.home()
    candidates = [
        home / ".zshrc",
        home / ".bashrc",
        home / ".profile",
        home / ".bash_profile",
    ]
    return [f for f in candidates if f.exists()]


def _build_copium_env_block(port: int) -> str:
    """Build the copium env var block to insert into shell rc files."""
    return (
        f"{_COPIUM_ENV_MARKER_START}\n"
        f'export ANTHROPIC_BASE_URL="http://127.0.0.1:{port}"\n'
        f'export OPENAI_API_BASE="http://127.0.0.1:{port}/v1"\n'
        f"{_COPIUM_ENV_MARKER_END}"
    )


def _patch_shell_rc_files(port: int) -> list[Path]:
    """Patch shell rc files with copium env vars. Returns list of patched files."""
    block = _build_copium_env_block(port)
    patched: list[Path] = []

    for rc_file in _get_user_shell_rc_files():
        try:
            content = rc_file.read_text(encoding="utf-8") if rc_file.exists() else ""
            if _COPIUM_ENV_MARKER_START in content:
                content = _COPIUM_ENV_PATTERN.sub(block, content)
            else:
                content = content.rstrip() + "\n\n" + block + "\n"
            rc_file.write_text(content, encoding="utf-8")
            patched.append(rc_file)
            logger.debug("patched shell rc: %s", rc_file)
        except Exception as e:
            logger.debug("failed to patch %s: %s", rc_file, e)

    return patched


def _remove_copium_from_shell_rc_files() -> list[Path]:
    """Remove copium env var blocks from shell rc files. Returns list of cleaned files."""
    cleaned: list[Path] = []

    for rc_file in _get_user_shell_rc_files():
        try:
            if not rc_file.exists():
                continue
            content = rc_file.read_text(encoding="utf-8")
            if _COPIUM_ENV_MARKER_START not in content:
                continue
            content = _COPIUM_ENV_PATTERN.sub("", content).strip() + "\n"
            rc_file.write_text(content, encoding="utf-8")
            cleaned.append(rc_file)
            logger.debug("cleaned shell rc: %s", rc_file)
        except Exception as e:
            logger.debug("failed to clean %s: %s", rc_file, e)

    return cleaned


def _create_global_config(port: int, backend: str) -> Path:
    """Create the global config at ~/.copium/config.toml."""
    _GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config_content = (
        "# Copium global configuration\n"
        "# Project-level config (copium.json) overrides these defaults.\n\n"
        "[proxy]\n"
        f"port = {port}\n"
        'host = "127.0.0.1"\n\n'
        "[compression]\n"
        'preset = "standard"\n'
        "quality_gate = true\n\n"
        "[dashboard]\n"
        "port = 8787\n"
        "open_on_start = false\n\n"
        "[telemetry]\n"
        "enabled = false  # opt-in only\n"
    )

    _GLOBAL_CONFIG_PATH.write_text(config_content, encoding="utf-8")
    logger.debug("created global config: %s", _GLOBAL_CONFIG_PATH)
    return _GLOBAL_CONFIG_PATH


def _remove_global_config() -> bool:
    """Remove the global config file. Returns True if removed."""
    if _GLOBAL_CONFIG_PATH.exists():
        _GLOBAL_CONFIG_PATH.unlink()
        logger.debug("removed global config: %s", _GLOBAL_CONFIG_PATH)
        return True
    return False


# ── §9a: shell prompt integration helpers ────────────────────────────────────

_COPIUM_PROMPT_MARKER_START = "# >>> copium prompt start <<<"
_COPIUM_PROMPT_MARKER_END   = "# >>> copium prompt end <<<"
_COPIUM_PROMPT_PATTERN = re.compile(
    re.escape(_COPIUM_PROMPT_MARKER_START) + r".*?" + re.escape(_COPIUM_PROMPT_MARKER_END),
    re.DOTALL,
)

# Starship TOML block that adds a [custom.copium] module
_STARSHIP_COPIUM_MODULE = """
# Copium active status indicator (§9a)
[custom.copium]
description = "Copium compression proxy status"
command     = "copium status --prompt"
when        = "copium ping"
format      = "[$output]($style) "
style       = "bold yellow"
""".strip()

# Shell function snippet for non-Starship prompts (bash/zsh PROMPT_COMMAND)
_SHELL_PROMPT_SNIPPET = """\
{marker_start}
# Copium active status indicator — shows ⚡ 38% in your prompt when proxy is running
_copium_prompt() {{
  local _s
  _s="$(copium status --prompt 2>/dev/null)"
  echo "${{_s:+[$_s] }}"
}}
PROMPT_COMMAND='_copium_prompt_val=$(_copium_prompt); ${{PROMPT_COMMAND:-:}}'
export PS1='${{_copium_prompt_val}}${{PS1}}'
{marker_end}"""


def _starship_config_path() -> Path:
    """Return the Starship config path (honours $STARSHIP_CONFIG env var)."""
    env = os.environ.get("STARSHIP_CONFIG")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "starship.toml"
    return Path.home() / ".config" / "starship.toml"


def _patch_starship_config() -> bool:
    """Inject a [custom.copium] module into starship.toml. Returns True on success."""
    star_cfg = _starship_config_path()
    try:
        content = star_cfg.read_text(encoding="utf-8") if star_cfg.exists() else ""
        if "[custom.copium]" in content:
            return True  # already present
        content = content.rstrip() + "\n\n" + _STARSHIP_COPIUM_MODULE + "\n"
        star_cfg.parent.mkdir(parents=True, exist_ok=True)
        star_cfg.write_text(content, encoding="utf-8")
        logger.debug("patched starship config: %s", star_cfg)
        return True
    except Exception as exc:
        logger.debug("failed to patch starship config: %s", exc)
        return False


def _remove_starship_copium_module() -> bool:
    """Remove the [custom.copium] block from starship.toml. Returns True if found."""
    star_cfg = _starship_config_path()
    if not star_cfg.exists():
        return False
    try:
        content = star_cfg.read_text(encoding="utf-8")
        if "[custom.copium]" not in content:
            return False
        # Strip the block (from [custom.copium] up to the next [ section or EOF)
        import re as _re
        content = _re.sub(
            r"\n*# Copium active status indicator[^\[]*?\[custom\.copium\][^\[]+",
            "\n",
            content,
            flags=_re.DOTALL,
        )
        star_cfg.write_text(content.rstrip() + "\n", encoding="utf-8")
        return True
    except Exception as exc:
        logger.debug("failed to remove starship copium module: %s", exc)
        return False


def _patch_shell_rc_prompt(rc_file: Path) -> bool:
    """Inject the _copium_prompt shell function into an rc file. Returns True on success."""
    try:
        content = rc_file.read_text(encoding="utf-8") if rc_file.exists() else ""
        if _COPIUM_PROMPT_MARKER_START in content:
            return True  # already present
        snippet = _SHELL_PROMPT_SNIPPET.format(
            marker_start=_COPIUM_PROMPT_MARKER_START,
            marker_end=_COPIUM_PROMPT_MARKER_END,
        )
        content = content.rstrip() + "\n\n" + snippet + "\n"
        rc_file.write_text(content, encoding="utf-8")
        logger.debug("patched shell rc with prompt: %s", rc_file)
        return True
    except Exception as exc:
        logger.debug("failed to patch rc with prompt: %s", exc)
        return False


def _remove_shell_rc_prompt(rc_file: Path) -> bool:
    """Remove the _copium_prompt block from an rc file. Returns True if removed."""
    try:
        if not rc_file.exists():
            return False
        content = rc_file.read_text(encoding="utf-8")
        if _COPIUM_PROMPT_MARKER_START not in content:
            return False
        content = _COPIUM_PROMPT_PATTERN.sub("", content).strip() + "\n"
        rc_file.write_text(content, encoding="utf-8")
        return True
    except Exception as exc:
        logger.debug("failed to remove prompt from rc: %s", exc)
        return False


def _offer_shell_prompt_integration(rc_files: list[Path]) -> None:
    """Interactively offer to set up shell prompt integration (§9a).

    Detects Starship automatically and patches its config. Falls back to
    injecting a shell function into the first writable rc file.
    """
    has_starship = bool(shutil.which("starship"))
    star_cfg = _starship_config_path()

    click.echo()
    click.secho("  Shell prompt integration", bold=True)
    if has_starship:
        click.echo(
            f"  Starship detected. Copium can add a '⚡ 38%' segment\n"
            f"  to your prompt when the proxy is active."
        )
        click.echo(f"  Config: {star_cfg}")
    else:
        click.echo(
            "  Copium can show '⚡ 38%' in your shell prompt (PS1)\n"
            "  when the proxy is active. Works with bash and zsh."
        )
    click.echo()

    if not click.confirm("  Set up shell prompt integration?", default=False):
        click.secho("  Skipped. Enable later with: copium status --prompt", dim=True)
        return

    if has_starship:
        if _patch_starship_config():
            click.secho(f"  ✓ Starship config updated ({star_cfg})", fg="green")
            click.echo("    Restart your shell to activate.")
        else:
            click.secho("  ✗ Could not update Starship config — check permissions.", fg="red")
    else:
        patched = False
        for rc in rc_files:
            if _patch_shell_rc_prompt(rc):
                click.secho(f"  ✓ Prompt integration added to {rc}", fg="green")
                patched = True
                break
        if not patched:
            click.secho("  ✗ Could not patch any shell rc file.", fg="red")
            click.echo("    Add manually to ~/.zshrc:")
            click.secho(
                "    PROMPT_COMMAND='_copium_val=$(copium status --prompt 2>/dev/null); : ${PROMPT_COMMAND}'",
                fg="yellow",
            )
            click.secho("    export PS1='${_copium_val}${PS1}'", fg="yellow")


def _print_next_steps(patched_rc_files: list[Path], config_path: Path, targets: list[str]) -> None:
    """Print the confirmation and next steps after successful init."""
    click.echo()
    click.secho("  Setup complete!", fg="green", bold=True)
    click.echo()

    if patched_rc_files:
        for rc_file in patched_rc_files:
            click.secho(f"  ✓ Shell config updated ({rc_file})", fg="green")

    if config_path.exists():
        click.secho(f"  ✓ Global config written ({config_path})", fg="green")

    click.echo()
    click.secho("  Next steps:", bold=True)
    click.echo()

    click.echo("  1. Reload your shell:")
    click.secho("     source ~/.zshrc  # or ~/.bashrc", fg="yellow")
    click.echo()
    click.echo("  2. Start your agent normally - Copium will be active automatically:")
    for target in targets:
        click.secho(f"     {target}", fg="yellow")
    click.echo()
    click.echo("  3. View savings at any time:")
    click.secho("     copium status", fg="yellow")
    click.echo()
    click.secho("  Tip:", dim=True, nl=False)
    click.secho(
        " Show '⚡ 38%' in your shell prompt: copium status --prompt",
        dim=True,
    )
    click.echo()


def _command_string(parts: list[str]) -> str:
    if os.name == "nt":
        # Normalize backslash paths to forward slashes so hook commands
        # work when Claude Code executes them via Git Bash (#724).
        parts = [p.replace("\\", "/") for p in parts]
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _hook_command(*parts: str) -> str:
    return _command_string([*resolve_copium_command(), "init", "hook", "ensure", *parts])


def _powershell_matcher() -> str:
    return "Bash|PowerShell" if os.name == "nt" else "Bash"


def _enable_verbose_logging() -> None:
    """Attach a stderr handler to the init logger at DEBUG level.

    Idempotent: calling this multiple times in one process (e.g. when nested
    subcommands are invoked) leaves exactly one handler attached. Does NOT
    mutate stdout; all verbose output goes to stderr so ``copium init``
    can still be composed in pipes that consume stdout.
    """

    if getattr(logger, _VERBOSE_HANDLER_ATTR, None) is not None:
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("[copium init] %(message)s"))
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    setattr(logger, _VERBOSE_HANDLER_ATTR, handler)


def _local_profile(cwd: Path | None = None) -> str:
    root = (cwd or Path.cwd()).resolve()
    slug = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in root.name.lower()).strip(
        "-"
    )
    digest = sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return validate_profile_name(f"init-{slug or 'repo'}-{digest}")


def _runtime_profile(global_scope: bool, cwd: Path | None = None) -> str:
    return _GLOBAL_PROFILE if global_scope else _local_profile(cwd)


def _copilot_config_path() -> Path:
    return Path.home() / ".copilot" / "config.json"


def _codex_hooks_path(global_scope: bool) -> Path:
    return (Path.home() if global_scope else Path.cwd()) / ".codex" / "hooks.json"


def _claude_scope_path(global_scope: bool) -> Path:
    if global_scope:
        return claude_settings_path()
    return Path.cwd() / ".claude" / "settings.local.json"


def _codex_scope_path(global_scope: bool) -> Path:
    if global_scope:
        return codex_config_path()
    return Path.cwd() / ".codex" / "config.toml"


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    payload = json.loads(content)
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    logger.debug("write json: %s (keys=%s)", path, sorted(payload.keys()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _ensure_claude_hooks(path: Path, profile: str, port: int) -> None:
    logger.debug("ensure claude hooks: %s (profile=%s, port=%s)", path, profile, port)
    payload = _json_file(path)
    env_map = dict(payload.get("env") or {}) if isinstance(payload.get("env"), dict) else {}
    env_map["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    # GH #746: with a custom ANTHROPIC_BASE_URL and ENABLE_TOOL_SEARCH unset,
    # Claude Code stops deferring MCP/system tool schemas and materializes them
    # all into its context window — overflowing it (breaks sub-agent spawns,
    # forces constant compaction). Keep deferral on; respect a user-set value.
    # Shares the TOOL_SEARCH_* constants with `wrap` and `install`.
    env_map.setdefault(TOOL_SEARCH_ENV, TOOL_SEARCH_DEFAULT)
    payload["env"] = env_map

    hooks = dict(payload.get("hooks") or {}) if isinstance(payload.get("hooks"), dict) else {}
    command = _hook_command("--profile", profile)
    for event, matcher in (
        ("SessionStart", "startup|resume"),
        ("PreToolUse", _powershell_matcher()),
    ):
        entries = list(hooks.get(event) or []) if isinstance(hooks.get(event), list) else []
        retained: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                retained.append(entry)
                continue
            hook_items = entry.get("hooks")
            if not isinstance(hook_items, list):
                retained.append(entry)
                continue
            has_copium = any(
                isinstance(item, dict)
                and item.get("command")
                and _CLAUDE_HOOK_MARKER in str(item.get("command"))
                for item in hook_items
            )
            if not has_copium:
                retained.append(entry)
        retained.append(
            {
                "matcher": matcher,
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{command} --marker {_CLAUDE_HOOK_MARKER}",
                        "timeout": 15,
                    }
                ],
            }
        )
        hooks[event] = retained
    payload["hooks"] = hooks
    _write_json(path, payload)


def _ensure_copilot_hooks(path: Path, profile: str) -> None:
    logger.debug("ensure copilot hooks: %s (profile=%s)", path, profile)
    payload = _json_file(path)
    hooks = dict(payload.get("hooks") or {}) if isinstance(payload.get("hooks"), dict) else {}
    command = f"{_hook_command('--profile', profile)} --marker {_COPILOT_HOOK_MARKER}"
    for event in ("SessionStart", "PreToolUse"):
        entries = list(hooks.get(event) or []) if isinstance(hooks.get(event), list) else []
        retained = [
            entry
            for entry in entries
            if not (
                isinstance(entry, dict) and _COPILOT_HOOK_MARKER in str(entry.get("command", ""))
            )
        ]
        retained.append({"type": "command", "command": command, "cwd": ".", "timeout": 15})
        hooks[event] = retained
    payload["hooks"] = hooks
    _write_json(path, payload)


def _replace_marker_block(
    content: str, marker_start: str, marker_end: str, block: str, *, at_root: bool = False
) -> str:
    content = _remove_marker_block(content, marker_start, marker_end)
    block = block.strip()
    if at_root:
        # The block carries top-level keys, so it must sit above the first table
        # header; appended after a table (e.g. [features]) TOML scopes those keys
        # into that table and Codex rejects the config (#260).
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if _TOML_TABLE_HEADER_RE.search(line):
                head = "\n".join(lines[:index]).rstrip()
                tail = "\n".join(lines[index:]).lstrip("\n")
                prefix = f"{head}\n\n" if head else ""
                return (f"{prefix}{block}\n\n{tail}").rstrip() + "\n"
    return (content.rstrip() + "\n\n" + block + "\n").lstrip()


def _remove_marker_block(content: str, marker_start: str, marker_end: str) -> str:
    if marker_start not in content or marker_end not in content:
        return content
    start = content.index(marker_start)
    end = content.index(marker_end) + len(marker_end)
    return content[:start].rstrip() + "\n\n" + content[end:].lstrip()


def _strip_codex_init_block(content: str) -> str:
    """Remove all Copium init-managed blocks and orphan keys from a Codex config.toml string."""
    import re

    # Remove any provider marker → end marker span, possibly repeated.
    while _CODEX_PROVIDER_MARKER_START in content and _CODEX_PROVIDER_MARKER_END in content:
        start = content.index(_CODEX_PROVIDER_MARKER_START)
        end_idx = content.index(_CODEX_PROVIDER_MARKER_END, start)
        if end_idx < start:
            break
        end = end_idx + len(_CODEX_PROVIDER_MARKER_END)
        content = content[:start].rstrip("\n") + "\n" + content[end:].lstrip("\n")

    # Remove stale unpaired markers.
    content = content.replace(_CODEX_PROVIDER_MARKER_START + "\n", "")
    content = content.replace(_CODEX_PROVIDER_MARKER_END + "\n", "")

    # Strip any orphan top-level keys that a crashed or partial write may have
    # left outside the marker block.
    content = re.sub(r'(?m)^[ \t]*model_provider[ \t]*=[ \t]*"copium"[ \t]*\r?\n', "", content)
    content = re.sub(
        r'(?m)^[ \t]*openai_base_url[ \t]*=[ \t]*"http://127\.0\.0\.1:\d+/v1"[ \t]*\r?\n',
        "",
        content,
    )

    # Strip any orphaned [model_providers.copium] table that is recognisably ours.
    orphan_copium_table = re.compile(
        r"(?ms)^\[model_providers\.copium\][^\[]*?"
        r'base_url[ \t]*=[ \t]*"http://127\.0\.0\.1:\d+/v1"[^\[]*?'
        r"(?=^\[|\Z)"
    )
    content = orphan_copium_table.sub("", content)

    return content.lstrip("\n").rstrip() + "\n" if content.strip() else ""


def _ensure_codex_provider(path: Path, port: int) -> None:
    import re

    logger.debug("ensure codex provider block: %s (port=%s)", path, port)
    # Emit requires_openai_auth only for ChatGPT-OAuth users (restores the
    # account menu); omitting it for API-key users avoids forcing an OAuth
    # login (#406).
    requires_openai_auth = (
        "requires_openai_auth = true\n"
        if codex_uses_chatgpt_auth(path.parent / "auth.json")
        else ""
    )
    block = (
        f"{_CODEX_PROVIDER_MARKER_START}\n"
        'model_provider = "copium"\n'
        f'openai_base_url = "http://127.0.0.1:{port}/v1"\n\n'
        "[model_providers.copium]\n"
        'name = "Copium init proxy"\n'
        f'base_url = "http://127.0.0.1:{port}/v1"\n'
        "supports_websockets = true\n"
        f"{requires_openai_auth}"
        f"{_CODEX_PROVIDER_MARKER_END}"
    )
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    # init owns model_provider/openai_base_url: drop any prior assignment (any
    # value, including one an older version mis-scoped under a table) so we
    # replace it instead of emitting a duplicate top-level key (#260).
    content = re.sub(r"(?m)^[ \t]*model_provider[ \t]*=.*\r?\n", "", content)
    content = re.sub(r"(?m)^[ \t]*openai_base_url[ \t]*=.*\r?\n", "", content)
    # The provider block carries top-level keys (model_provider, openai_base_url),
    # so it must land at the document root rather than after a trailing table (#260).
    content = _replace_marker_block(
        content, _CODEX_PROVIDER_MARKER_START, _CODEX_PROVIDER_MARKER_END, block, at_root=True
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _codex_feature_block() -> str:
    return f"{_CODEX_FEATURE_MARKER_START}\nhooks = true\n{_CODEX_FEATURE_MARKER_END}"


def _codex_dotted_feature_block() -> str:
    return f"{_CODEX_FEATURE_MARKER_START}\nfeatures.hooks = true\n{_CODEX_FEATURE_MARKER_END}"


def _codex_features_table_index(lines: list[str]) -> int | None:
    return next(
        (index for index, line in enumerate(lines) if _CODEX_FEATURES_TABLE_RE.search(line)),
        None,
    )


def _codex_features(content: str) -> dict[str, Any] | None:
    if not content.strip():
        return None
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None
    features = parsed.get("features")
    return features if isinstance(features, dict) else None


def _codex_features_has_hooks(content: str) -> bool:
    features = _codex_features(content)
    if features is None:
        # Keep init resilient for already-invalid user configs; this fallback
        # only needs to avoid adding a second obvious hooks line.
        lines = content.splitlines()
        features_index = _codex_features_table_index(lines)
        if features_index is None:
            return False
        for line in lines[features_index + 1 :]:
            if _TOML_TABLE_HEADER_RE.search(line):
                break
            if re.search(r"^[ \t]*hooks[ \t]*=", line):
                return True
        return False

    return "hooks" in features


def _strip_codex_legacy_feature_flag(content: str) -> str:
    lines = content.splitlines(keepends=True)
    retained: list[str] = []
    in_features = False
    in_root = True

    for line in lines:
        if _TOML_TABLE_HEADER_RE.search(line):
            in_root = False
            in_features = bool(_CODEX_FEATURES_TABLE_RE.search(line))
            retained.append(line)
            continue
        if (in_root and _CODEX_FEATURES_DOTTED_LEGACY_RE.search(line)) or (
            in_features and _CODEX_FEATURES_LEGACY_KEY_RE.search(line)
        ):
            continue
        retained.append(line)

    return "".join(retained)


def _ensure_codex_feature_flag(path: Path) -> None:
    """Ensure Codex's ``[features].hooks`` flag is enabled in config.toml.

    ``hooks`` is the canonical key. ``codex_hooks`` was the original key name and
    still resolves as a deprecated alias, but Codex >= 0.129 emits a deprecation
    warning for it (renamed in openai/codex#20522). Any legacy
    ``[features].codex_hooks`` line is removed, whether inside or outside our
    marker block, so a migrated config drops the deprecated key and never
    collides with a duplicate ``hooks`` key. A user-managed ``hooks`` value
    outside our marker block is left untouched.
    """
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    # Drop the deprecated alias key from [features]. Mirrors the top-level key
    # cleanup in _ensure_codex_provider (#260) so re-running init migrates a
    # legacy config rather than producing a duplicate `hooks` key, while leaving
    # unrelated user tables untouched.
    content = _strip_codex_legacy_feature_flag(content)
    if _CODEX_FEATURE_MARKER_START in content and _CODEX_FEATURE_MARKER_END in content:
        # init owns its marker block; remove it first, then reinsert under the
        # correct TOML scope below.
        content = _remove_marker_block(
            content, _CODEX_FEATURE_MARKER_START, _CODEX_FEATURE_MARKER_END
        )

    if _codex_features_has_hooks(content):
        # A user-managed `[features].hooks` key already exists outside our
        # marker block; respect their value. Clearing the legacy key above was
        # the only work.
        pass
    else:
        lines = content.splitlines()
        features_index = _codex_features_table_index(lines)
        if features_index is not None:
            # Leading blank line matches the normalisation _replace_marker_block
            # applies on later runs, so re-running init is byte-idempotent.
            lines[features_index + 1 : features_index + 1] = [
                "",
                *_codex_feature_block().splitlines(),
            ]
            content = "\n".join(lines).rstrip() + "\n"
        elif _codex_features(content) is not None:
            # The user expressed [features] via dotted keys, so adding a new
            # table would duplicate it. Keep this key at the document root.
            content = _replace_marker_block(
                content,
                _CODEX_FEATURE_MARKER_START,
                _CODEX_FEATURE_MARKER_END,
                _codex_dotted_feature_block(),
                at_root=True,
            )
        else:
            content = (
                content.rstrip() + "\n\n[features]\n\n" + _codex_feature_block() + "\n"
            ).lstrip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_codex_hooks(path: Path, profile: str) -> None:
    logger.debug("ensure codex hooks: %s (profile=%s)", path, profile)
    command = f"{_hook_command('--profile', profile)} --marker {_CODEX_HOOK_MARKER}"
    payload = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume",
                    "hooks": [{"type": "command", "command": command, "timeout": 15}],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": command, "timeout": 15}],
                }
            ],
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _manifest_changed(
    existing: Any,
    *,
    port: int,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
) -> bool:
    return any(
        [
            getattr(existing, "port", port) != port,
            getattr(existing, "backend", backend) != backend,
            getattr(existing, "anyllm_provider", anyllm_provider) != anyllm_provider,
            getattr(existing, "region", region) != region,
            getattr(existing, "memory_enabled", memory) != memory,
        ]
    )


def _ensure_runtime_manifest(
    *,
    global_scope: bool,
    targets: list[str],
    port: int,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
) -> str:
    profile = _runtime_profile(global_scope)
    existing = load_manifest(profile)
    merged_targets = sorted(set(existing.targets if existing else []).union(targets))
    manifest = build_manifest(
        profile=profile,
        preset=InstallPreset.PERSISTENT_TASK.value,
        runtime_kind=RuntimeKind.PYTHON.value,
        scope=ConfigScope.USER.value,
        provider_mode="manual",
        targets=merged_targets,
        port=port,
        backend=backend,
        anyllm_provider=anyllm_provider,
        region=region,
        proxy_mode="token",
        memory_enabled=memory,
        telemetry_enabled=False,  # Default OFF for privacy
        image="ghcr.io/iKislay/copium:latest",
    )
    manifest.supervisor_kind = SupervisorKind.NONE.value
    manifest.artifacts = []
    manifest.mutations = existing.mutations if existing else []
    if existing is not None and _manifest_changed(
        existing,
        port=port,
        backend=backend,
        anyllm_provider=anyllm_provider,
        region=region,
        memory=memory,
    ):
        try:
            stop_runtime(existing)
        except Exception:
            pass
    save_manifest(manifest)
    return profile


def _env_manifest(values: dict[str, str]) -> Any:
    return build_manifest(
        profile="init-env",
        preset=InstallPreset.PERSISTENT_TASK.value,
        runtime_kind=RuntimeKind.PYTHON.value,
        scope=ConfigScope.USER.value,
        provider_mode="manual",
        targets=["copilot"],
        port=8787,
        backend="anthropic",
        anyllm_provider=None,
        region=None,
        proxy_mode="token",
        memory_enabled=False,
        telemetry_enabled=False,  # Default OFF for privacy
        image="ghcr.io/iKislay/copium:latest",
    )


def _apply_user_env(values: dict[str, str]) -> None:
    manifest = _env_manifest(values)
    manifest.base_env = {}
    manifest.tool_envs = {"copilot": values}
    scope = "windows" if os.name == "nt" else "unix"
    logger.debug("apply user env scope=%s keys=%s", scope, sorted(values.keys()))
    if os.name == "nt":
        _apply_windows_env_scope(manifest)
    else:
        _apply_unix_env_scope(manifest)


def _resolve_copilot_env(port: int, backend: str) -> dict[str, str]:
    if backend == "anthropic":
        return {
            "COPILOT_PROVIDER_TYPE": "anthropic",
            "COPILOT_PROVIDER_BASE_URL": f"http://127.0.0.1:{port}",
        }
    return {
        "COPILOT_PROVIDER_TYPE": "openai",
        "COPILOT_PROVIDER_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "COPILOT_PROVIDER_WIRE_API": "completions",
    }


def _marketplace_source() -> str:
    override = os.environ.get("COPIUM_MARKETPLACE_SOURCE")
    if override:
        return override
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / ".claude-plugin" / "marketplace.json").exists():
        return str(repo_root)
    return "iKislay/copium"


def _run_checked(command: list[str], *, action: str) -> None:
    logger.debug("subprocess [%s]: %s", action, _command_string(command))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    logger.debug(
        "subprocess [%s] exit=%s stdout=%r stderr=%r",
        action,
        result.returncode,
        result.stdout[:200],
        result.stderr[:200],
    )
    if result.returncode == 0:
        return
    detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
    if "already" in detail.lower() or "exists" in detail.lower():
        logger.debug(
            "subprocess [%s] non-zero exit tolerated ('already'/'exists' detected)", action
        )
        return
    raise click.ClickException(f"{action} failed: {detail or result.returncode}")


def _install_claude_marketplace(scope: str) -> None:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise click.ClickException("'claude' not found in PATH. Install Claude Code first.")
    source = _marketplace_source()
    _run_checked(
        [claude_bin, "plugin", "marketplace", "add", source], action="claude marketplace add"
    )
    _run_checked(
        [claude_bin, "plugin", "install", "copium@copium-marketplace", "--scope", scope],
        action="claude plugin install",
    )


def _install_copilot_marketplace() -> None:
    copilot_bin = shutil.which("copilot")
    if not copilot_bin:
        raise click.ClickException("'copilot' not found in PATH. Install GitHub Copilot CLI first.")
    source = _marketplace_source()
    _run_checked(
        [copilot_bin, "plugin", "marketplace", "add", source],
        action="copilot marketplace add",
    )
    _run_checked(
        [copilot_bin, "plugin", "install", "copium@copium-marketplace"],
        action="copilot plugin install",
    )


@contextmanager
def _suppress_hook_output() -> Iterator[None]:
    """Keep best-effort hook recovery from emitting invalid hook output."""
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(devnull.fileno(), 1)
            os.dup2(devnull.fileno(), 2)
            with redirect_stdout(devnull), redirect_stderr(devnull):
                yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)


def _ensure_profile_running(profile: str) -> None:
    manifest = load_manifest(profile)
    if manifest is None:
        return
    with _suppress_hook_output():
        if wait_ready(manifest, timeout_seconds=1):
            return
        try:
            with acquire_runtime_start_lock(manifest.profile) as acquired:
                if not acquired:
                    return
                if wait_ready(manifest, timeout_seconds=1):
                    return
                if runtime_status(manifest) == "running":
                    if wait_ready(manifest, timeout_seconds=_STARTUP_READY_TIMEOUT_SECONDS):
                        return
                    stop_runtime(manifest)
                if manifest.preset == InstallPreset.PERSISTENT_DOCKER.value:
                    start_persistent_docker(manifest)
                elif manifest.supervisor_kind == SupervisorKind.SERVICE.value:
                    start_supervisor(manifest)
                else:
                    start_detached_agent(manifest.profile)
                wait_ready(manifest, timeout_seconds=45)
        except Exception:
            return


def _probe_init_targets(global_scope: bool) -> list[tuple[str, str | None]]:
    """Return ``[(target, which_result)]`` for every in-scope supported target.

    ``which_result`` is the absolute path reported by :func:`shutil.which`, or
    ``None`` when the binary is not on PATH. Callers use the list both to
    build an auto-detected target list and to produce a diagnostic error
    message when nothing was found.
    """

    allowed = _GLOBAL_TARGETS if global_scope else _LOCAL_TARGETS
    logger.debug(
        "detect_init_targets: global_scope=%s allowed=%s",
        global_scope,
        sorted(allowed),
    )
    probes: list[tuple[str, str | None]] = []
    for target in _SUPPORTED_TARGETS:
        if target not in allowed:
            continue
        path = shutil.which(target)
        logger.debug("detect_init_targets: shutil.which(%r) -> %s", target, path or "None")
        probes.append((target, path))
    return probes


def detect_init_targets(global_scope: bool) -> list[str]:
    """Return agent names in scope for which a binary was found on PATH."""

    return [name for name, path in _probe_init_targets(global_scope) if path]


def _format_empty_detection_error(global_scope: bool) -> str:
    """Build the error message shown when no in-scope targets were detected.

    Lists every agent that was probed, what ``shutil.which`` returned, and
    confirms how to proceed explicitly — including that the ``-g`` / ``--global``
    flag the user tried is still valid.
    """

    probes = _probe_init_targets(global_scope)
    scope_flag = "-g" if global_scope else ""
    scope_label = "user" if global_scope else "local"

    lines: list[str] = [
        f"No supported {scope_label}-scope agents were found on PATH.",
        "",
        "Copium probed the following agents via shutil.which():",
    ]
    for name, path in probes:
        status = f"found at {path}" if path else "not found"
        lines.append(f"  - {name}: {status}")

    lines.extend(
        [
            "",
            f"The {scope_flag or '--local (no flag)'} option is still supported; "
            "copium init just needs to know which agent to target.",
            "Install the agent you want first, then re-run with an explicit target:",
            "",
        ]
    )
    for name, _path in probes:
        flag = " -g" if global_scope else ""
        lines.append(f"  copium init{flag} {name}")

    lines.extend(
        [
            "",
            "Tip: run `copium init --help` to see all options.",
        ]
    )
    return "\n".join(lines)


def _init_claude(*, global_scope: bool, profile: str, port: int) -> None:
    _ensure_claude_hooks(_claude_scope_path(global_scope), profile, port)
    _install_claude_marketplace("user" if global_scope else "local")
    click.echo(f"Configured Claude Code ({'user' if global_scope else 'local'} scope).")
    click.echo("Restart Claude Code to activate Copium hooks and provider routing.")


def _init_copilot(*, global_scope: bool, profile: str, port: int, backend: str) -> None:
    if not global_scope:
        raise click.ClickException(
            "Copilot durable init currently requires -g (current-user scope)."
        )
    _ensure_copilot_hooks(_copilot_config_path(), profile)
    _apply_user_env(_resolve_copilot_env(port, backend))
    _install_copilot_marketplace()
    click.echo("Configured GitHub Copilot CLI (user scope).")
    click.echo("Restart Copilot CLI to activate Copium hooks and provider routing.")


def _init_codex(*, global_scope: bool, profile: str, port: int) -> None:
    config_path = _codex_scope_path(global_scope)
    _ensure_codex_provider(config_path, port)
    _ensure_codex_feature_flag(config_path)
    _ensure_codex_hooks(_codex_hooks_path(global_scope), profile)
    click.echo(f"Configured Codex ({'user' if global_scope else 'local'} scope).")
    if os.name == "nt":
        click.echo(
            "Codex hooks are currently disabled upstream on Windows; provider routing was still installed."
        )
    click.echo("Restart Codex to activate Copium configuration.")


def _init_openclaw(*, global_scope: bool, port: int) -> None:
    if not global_scope:
        raise click.ClickException(
            "OpenClaw durable init currently requires -g (current-user scope)."
        )
    command = [*resolve_copium_command(), "wrap", "openclaw", "--proxy-port", str(port)]
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _resolve_cursor_env(port: int) -> dict[str, str]:
    return {
        "OPENAI_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
    }


def _resolve_aider_env(port: int) -> dict[str, str]:
    return {
        "OPENAI_API_BASE": f"http://127.0.0.1:{port}/v1",
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
    }


def _init_cursor(*, global_scope: bool, port: int, backend: str) -> None:
    env = _resolve_cursor_env(port)
    _apply_user_env(env)
    click.echo("Configured Cursor environment variables.")
    click.echo(f"  OPENAI_BASE_URL={env['OPENAI_BASE_URL']}")
    click.echo(f"  ANTHROPIC_BASE_URL={env['ANTHROPIC_BASE_URL']}")
    click.echo("Restart Cursor to activate Copium proxy routing.")


def _init_aider(*, global_scope: bool, port: int, backend: str) -> None:
    env = _resolve_aider_env(port)
    _apply_user_env(env)
    click.echo("Configured Aider environment variables.")
    click.echo(f"  OPENAI_API_BASE={env['OPENAI_API_BASE']}")
    click.echo(f"  ANTHROPIC_BASE_URL={env['ANTHROPIC_BASE_URL']}")
    click.echo("Restart Aider to activate Copium proxy routing.")


def _run_init_targets(
    *,
    targets: list[str],
    global_scope: bool,
    port: int,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
    skip_shell_rc: bool = False,
    skip_global_config: bool = False,
) -> None:
    logger.debug(
        "run_init_targets: targets=%s global_scope=%s port=%s backend=%s memory=%s",
        targets,
        global_scope,
        port,
        backend,
        memory,
    )
    runtime_targets = [target for target in targets if target != "openclaw"]
    profile = _ensure_runtime_manifest(
        global_scope=global_scope,
        targets=runtime_targets,
        port=port,
        backend=backend,
        anyllm_provider=anyllm_provider,
        region=region,
        memory=memory,
    )
    logger.debug("run_init_targets: using profile=%s", profile)
    for target in targets:
        logger.debug("run_init_targets: dispatching -> %s", target)
        if target == "claude":
            _init_claude(global_scope=global_scope, profile=profile, port=port)
        elif target == "copilot":
            _init_copilot(global_scope=global_scope, profile=profile, port=port, backend=backend)
        elif target == "codex":
            _init_codex(global_scope=global_scope, profile=profile, port=port)
        elif target == "openclaw":
            _init_openclaw(global_scope=global_scope, port=port)
        elif target == "cursor":
            _init_cursor(global_scope=global_scope, port=port, backend=backend)
        elif target == "aider":
            _init_aider(global_scope=global_scope, port=port, backend=backend)

    # Register the copium MCP server with every targeted agent that has
    # a registrar implemented. Wave 1 covers Claude Code; subsequent waves
    # add Cursor / Codex / Continue / Cline / Windsurf / Goose without
    # touching the call sites.
    _install_copium_mcp_for_targets(targets=targets, port=port)

    # Plan §3a: Patch shell rc files with env vars and create global config
    patched_rc_files: list[Path] = []
    config_path = _GLOBAL_CONFIG_PATH

    if not skip_shell_rc and global_scope:
        patched_rc_files = _patch_shell_rc_files(port)

    if not skip_global_config:
        config_path = _create_global_config(port, backend)

    _print_next_steps(patched_rc_files, config_path, targets)

    # §9a: offer shell prompt integration after setup (global scope only)
    if global_scope and not skip_shell_rc:
        _offer_shell_prompt_integration(_get_user_shell_rc_files())


def _install_copium_mcp_for_targets(*, targets: list[str], port: int) -> None:
    """Install the copium MCP server into each detected target agent."""
    from copium.mcp_registry import format_results, install_everywhere

    proxy_url = f"http://127.0.0.1:{port}"
    results = install_everywhere(proxy_url=proxy_url, agents=targets)
    if not results:
        return

    lines = format_results(
        results,
        verbose=True,
        overwrite_hint=f"copium mcp install --proxy-url {proxy_url} --force",
    )
    if lines:
        click.echo("\nMCP retrieve tool:")
        for line in lines:
            click.echo(line)


@main.group(invoke_without_command=True)
@click.option("-g", "--global", "global_scope", is_flag=True, help="Install for the current user.")
@click.option("--port", default=8787, type=int, show_default=True, help="Copium proxy port.")
@click.option("--backend", default="anthropic", show_default=True, help="Proxy backend.")
@click.option("--anyllm-provider", default=None, help="Provider for any-llm backends.")
@click.option("--region", default=None, help="Cloud region for Bedrock / Vertex style backends.")
@click.option("--memory", is_flag=True, help="Enable persistent memory in the proxy runtime.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be configured without making changes.",
)
@click.option(
    "--skip-shell-rc",
    is_flag=True,
    help="Skip patching shell rc files with env vars.",
)
@click.option(
    "--skip-global-config",
    is_flag=True,
    help="Skip creating global config at ~/.copium/config.toml.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Emit debug-level diagnostics to stderr (flag values, shutil.which results, "
    "file paths touched, subprocess invocations and exit codes).",
)
@click.pass_context
def init(
    ctx: click.Context,
    global_scope: bool,
    port: int,
    backend: str,
    anyllm_provider: str | None,
    region: str | None,
    memory: bool,
    dry_run: bool,
    skip_shell_rc: bool,
    skip_global_config: bool,
    verbose: bool,
) -> None:
    """Install durable Copium integrations for supported agents."""
    if verbose:
        _enable_verbose_logging()
    logger.debug(
        "init: global_scope=%s port=%s backend=%s anyllm_provider=%s region=%s memory=%s "
        "dry_run=%s skip_shell_rc=%s skip_global_config=%s invoked_subcommand=%s",
        global_scope,
        port,
        backend,
        anyllm_provider,
        region,
        memory,
        dry_run,
        skip_shell_rc,
        skip_global_config,
        ctx.invoked_subcommand,
    )
    if ctx.invoked_subcommand is not None:
        ctx.obj = {
            "global_scope": global_scope,
            "port": port,
            "backend": backend,
            "anyllm_provider": anyllm_provider,
            "region": region,
            "memory": memory,
            "dry_run": dry_run,
            "skip_shell_rc": skip_shell_rc,
            "skip_global_config": skip_global_config,
            "verbose": verbose,
        }
        return

    targets = detect_init_targets(global_scope)
    if not targets:
        logger.debug("init: detect_init_targets returned empty; exiting with guided error")
        raise click.ClickException(_format_empty_detection_error(global_scope))
    logger.debug("init: detected targets=%s", targets)

    if dry_run:
        click.echo("Dry run: would configure the following targets:")
        for target in targets:
            click.echo(f"  - {target}")
        click.echo(f"\nPort: {port}")
        click.echo(f"Backend: {backend}")
        click.echo(f"Memory: {'enabled' if memory else 'disabled'}")
        click.echo(f"Shell rc patching: {'enabled' if not skip_shell_rc else 'disabled'}")
        click.echo(f"Global config: {'enabled' if not skip_global_config else 'disabled'}")
        return

    _run_init_targets(
        targets=targets,
        global_scope=global_scope,
        port=port,
        backend=backend,
        anyllm_provider=anyllm_provider,
        region=region,
        memory=memory,
        skip_shell_rc=skip_shell_rc,
        skip_global_config=skip_global_config,
    )


def _ctx_value(ctx: click.Context, key: str) -> Any:
    return (ctx.obj or {}).get(key)


@init.command("claude")
@click.pass_context
def init_claude(ctx: click.Context) -> None:
    """Install Claude Code durable hooks and provider routing."""
    _run_init_targets(
        targets=["claude"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
    )


@init.command("copilot")
@click.pass_context
def init_copilot(ctx: click.Context) -> None:
    """Install GitHub Copilot CLI durable hooks and provider routing."""
    _run_init_targets(
        targets=["copilot"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
    )


@init.command("codex")
@click.pass_context
def init_codex(ctx: click.Context) -> None:
    """Install Codex durable hooks and provider routing."""
    _run_init_targets(
        targets=["codex"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
    )


@init.command("openclaw")
@click.pass_context
def init_openclaw(ctx: click.Context) -> None:
    """Install the durable OpenClaw Copium plugin."""
    _run_init_targets(
        targets=["openclaw"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
    )


@init.command("cursor")
@click.pass_context
def init_cursor(ctx: click.Context) -> None:
    """Install Cursor durable environment variables for Copium proxy routing."""
    _run_init_targets(
        targets=["cursor"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
    )


@init.command("aider")
@click.pass_context
def init_aider(ctx: click.Context) -> None:
    """Install Aider durable environment variables for Copium proxy routing."""
    _run_init_targets(
        targets=["aider"],
        global_scope=bool(_ctx_value(ctx, "global_scope")),
        port=int(_ctx_value(ctx, "port") or 8787),
        backend=str(_ctx_value(ctx, "backend") or "anthropic"),
        anyllm_provider=_ctx_value(ctx, "anyllm_provider"),
        region=_ctx_value(ctx, "region"),
        memory=bool(_ctx_value(ctx, "memory")),
    )


@init.group("hook", hidden=True)
def init_hook() -> None:
    """Internal hook helpers."""


@init_hook.command("ensure")
@click.option("--profile", default=None, help="Explicit deployment profile to ensure.")
@click.option("--marker", default=None, hidden=True)
def init_hook_ensure(profile: str | None, marker: str | None) -> None:
    """Best-effort ensure used by installed agent hooks."""
    del marker
    profiles: list[str] = []
    if profile:
        profiles.append(profile)
    else:
        local_profile = _local_profile()
        if load_manifest(local_profile) is not None:
            profiles.append(local_profile)
        elif load_manifest(_GLOBAL_PROFILE) is not None:
            profiles.append(_GLOBAL_PROFILE)
    for name in profiles:
        _ensure_profile_running(name)
