"""Hierarchical configuration loader for Copium.

Implements a two-tier config model (like .gitconfig + .git/config):

    ~/.copium/config.toml         Global defaults (always loaded)
    <project-root>/copium.json    Project overrides (loaded if present)

Project config wins on any key that both specify. The merged result is
a plain dict that CLI commands consume (port, backend, preset, etc.).

Usage::

    from copium.config_loader import load_merged_config, load_global_config

    # Get merged proxy defaults (apply CLI flags on top)
    defaults = load_proxy_defaults()
    # CLI flags override config-file values
    port = cli_port or defaults.get("proxy.port", 8787)

    # Get a fully resolved CopiumConfig (preset + overrides)
    from copium.config_loader import load_copium_config
    copium_cfg = load_copium_config(preset="aggressive", overrides={"compression.quality_gate": False})
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_GLOBAL_CONFIG_DIR = Path.home() / ".copium"
_GLOBAL_CONFIG_PATH = _GLOBAL_CONFIG_DIR / "config.toml"
_PROJECT_CONFIG_NAME = "copium.json"

# Flat shorthand keys → canonical dotted path
_FLAT_KEY_MAP: dict[str, str] = {
    "port": "proxy.port",
    "host": "proxy.host",
    "backend": "proxy.backend",
    "preset": "compression.preset",
    "quality_gate": "compression.quality_gate",
}


# ---------------------------------------------------------------------------
# TOML loading (Python 3.11+ has tomllib built-in)
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file into a plain dict."""
    if sys.version_info >= (3, 11):
        import tomllib

        with open(path, "rb") as f:
            return tomllib.load(f)
    else:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            raise ImportError(
                "tomli is required for Python < 3.11. "
                "Install it with: pip install tomli"
            ) from None
        with open(path, "rb") as f:
            return tomllib.load(f)


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """Write a dict as a TOML file (minimal, no external deps)."""
    lines: list[str] = []
    _render_toml_section(lines, data, prefix="")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def _render_toml_section(
    lines: list[str], data: dict[str, Any], prefix: str
) -> None:
    """Recursively render a dict as TOML sections."""
    simple: dict[str, Any] = {}
    nested: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            nested[k] = v
        else:
            simple[k] = v

    for k, v in simple.items():
        lines.append(f"{k} = {_toml_value(v)}\n")

    for k, v in nested.items():
        section = f"{prefix}.{k}" if prefix else k
        lines.append(f"\n[{section}]\n")
        _render_toml_section(lines, v, prefix=section)


def _toml_value(v: Any) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        inner = ", ".join(_toml_value(item) for item in v)
        return f"[{inner}]"
    return f'"{v}"'


# ---------------------------------------------------------------------------
# Config file reading
# ---------------------------------------------------------------------------


def load_global_config() -> dict[str, Any]:
    """Read and return the global config as a plain dict.

    Returns an empty dict if the file doesn't exist or can't be parsed.
    """
    if not _GLOBAL_CONFIG_PATH.exists():
        return {}
    try:
        return _load_toml(_GLOBAL_CONFIG_PATH)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", _GLOBAL_CONFIG_PATH, exc)
        return {}


def load_project_config(cwd: Path | None = None) -> dict[str, Any]:
    """Read and return the project-level copium.json as a plain dict.

    Searches upward from *cwd* (default: ``os.getcwd()``) for a
    ``copium.json`` file, stopping at the filesystem root or a
    ``.git`` / ``.svn`` boundary.

    Returns an empty dict if no project config is found.
    """
    start = Path(cwd) if cwd else Path.cwd()
    current = start.resolve()
    while True:
        candidate = current / _PROJECT_CONFIG_NAME
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", candidate, exc)
                return {}
        # Stop at filesystem root or VCS boundary
        if current == current.parent or (current / ".git").exists():
            break
        current = current.parent
    return {}


def find_project_config_path(cwd: Path | None = None) -> Path | None:
    """Return the path to the project config, or None if not found."""
    start = Path(cwd) if cwd else Path.cwd()
    current = start.resolve()
    while True:
        candidate = current / _PROJECT_CONFIG_NAME
        if candidate.exists():
            return candidate
        if current == current.parent or (current / ".git").exists():
            break
        current = current.parent
    return None


# ---------------------------------------------------------------------------
# Dict merging
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base* (mutates *base*)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# ---------------------------------------------------------------------------
# Public API: proxy defaults
# ---------------------------------------------------------------------------


def load_proxy_defaults(
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Load merged config as a flat dotted-key dict for proxy startup.

    Returns a dict like::

        {
            "proxy.port": 8082,
            "proxy.host": "127.0.0.1",
            "proxy.backend": "anthropic",
            "compression.preset": "standard",
            ...
        }

    CLI flags should override these values. This only returns values
    that are explicitly set in config files (not defaults).
    """
    global_cfg = load_global_config()
    project_cfg = load_project_config(cwd=cwd)

    global_flat = _flatten(global_cfg)
    project_flat = _flatten(project_cfg)

    # Project overrides global
    return _deep_merge(global_flat, project_flat)


# ---------------------------------------------------------------------------
# Public API: CopiumConfig construction
# ---------------------------------------------------------------------------


def load_copium_config(
    *,
    preset: str | None = None,
    overrides: dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> Any:  # -> CopiumConfig but avoiding circular import at module level
    """Build a ``CopiumConfig`` from config files + overrides.

    Merge order (last wins):
        1. CopiumConfig defaults (constructor)
        2. Named preset (if specified)
        3. Global config (``~/.copium/config.toml``)
        4. Project config (``<cwd>/copium.json``)
        5. Explicit *overrides* dict (CLI flags, etc.)

    Args:
        preset: Named preset ("standard", "aggressive", etc.).
            Overrides the preset in config files.
        overrides: Ad-hoc overrides as dotted-key dict.
        cwd: Project root for ``copium.json`` search.

    Returns:
        A fully resolved ``CopiumConfig`` instance.
    """
    from copium.config import CopiumConfig
    from copium.presets import ALL_PRESETS

    # 1. Start with defaults
    effective_preset = preset

    # 2. Check config files for preset if not given on CLI
    if effective_preset is None:
        merged_flat = load_proxy_defaults(cwd=cwd)
        effective_preset = merged_flat.get("compression.preset")

    # 3. Apply preset
    config: CopiumConfig
    if effective_preset and effective_preset in ALL_PRESETS:
        config = ALL_PRESETS[effective_preset]()
    else:
        config = CopiumConfig()

    # 4. Apply config file overrides (individual keys, not preset)
    merged_flat = load_proxy_defaults(cwd=cwd)
    _apply_copium_overrides(config, merged_flat)

    # 5. Apply explicit overrides (CLI flags)
    if overrides:
        _apply_copium_overrides(config, overrides)

    return config


def _apply_copium_overrides(config: Any, flat: dict[str, Any]) -> None:
    """Apply flat dotted-key overrides to a CopiumConfig instance.

    Only ``compression.*`` keys are applied — proxy-level keys like
    ``proxy.port`` are consumed by the proxy CLI, not CopiumConfig.
    """
    _COMPRESSION_ATTRS: dict[str, tuple[str, ...]] = {
        "compression.quality_gate": ("quality_gate", "enabled"),
        "compression.smart_crusher.max_items_after_crush": ("smart_crusher", "max_items_after_crush"),
        "compression.smart_crusher.min_tokens_to_crush": ("smart_crusher", "min_tokens_to_crush"),
        "compression.session_dedup.enabled": ("session_dedup", "enabled"),
        "compression.session_dedup.minhash_threshold": ("session_dedup", "minhash_threshold"),
        "compression.error_compressor.enabled": ("error_compressor", "enabled"),
        "compression.error_compressor.max_stack_frames": ("error_compressor", "max_stack_frames"),
        "compression.output_compressor.enabled": ("output_compressor", "enabled"),
        "compression.context_budget.enabled": ("context_budget", "enabled"),
    }

    for dotted_key, attr_path in _COMPRESSION_ATTRS.items():
        value = flat.get(dotted_key)
        if value is None:
            continue
        obj = config
        for attr in attr_path[:-1]:
            obj = getattr(obj, attr)
        setattr(obj, attr_path[-1], value)


# ---------------------------------------------------------------------------
# Public API: config inspection / editing
# ---------------------------------------------------------------------------


def get_config_sources() -> dict[str, Any]:
    """Return information about active config sources (for display)."""
    global_path = _GLOBAL_CONFIG_PATH
    project_path = find_project_config_path()

    return {
        "global": {
            "path": str(global_path),
            "exists": global_path.exists(),
        },
        "project": {
            "path": str(project_path) if project_path else None,
            "exists": project_path is not None,
        },
    }


def show_merged_flat(
    *,
    cwd: Path | None = None,
    global_only: bool = False,
) -> dict[str, Any]:
    """Return the resolved config as a flat dotted-key dict (for display)."""
    global_cfg = load_global_config()
    global_flat = _flatten(global_cfg)

    if global_only:
        return global_flat

    project_cfg = load_project_config(cwd=cwd)
    project_flat = _flatten(project_cfg)

    return _deep_merge(global_flat, project_flat)


def set_config_value(
    key: str,
    value: Any,
    *,
    global_scope: bool = False,
) -> Path:
    """Set a config value in the appropriate config file.

    Args:
        key: Dotted key (e.g. ``proxy.port``) or shorthand (e.g. ``port``).
        value: The value to set.
        global_scope: If True, write to global config; else project config.

    Returns:
        Path to the config file that was written.
    """
    # Normalize shorthand keys
    normalized = _FLAT_KEY_MAP.get(key, key)

    if global_scope:
        config_path = _GLOBAL_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        existing = load_global_config()
    else:
        project_path = find_project_config_path()
        config_path = project_path or (Path.cwd() / _PROJECT_CONFIG_NAME)
        existing = {}
        if project_path and project_path.exists():
            try:
                existing = json.loads(project_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

    # Set the value in the nested dict
    _set_nested_dict(existing, normalized, value)

    # Write back
    if global_scope:
        _write_toml(config_path, existing)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return config_path


def reset_config(*, global_scope: bool = False) -> Path:
    """Reset config to defaults by removing the config file.

    Returns the path that was removed (or would have been removed).
    """
    if global_scope:
        config_path = _GLOBAL_CONFIG_PATH
        if config_path.exists():
            config_path.unlink()
        return config_path
    else:
        project_path = find_project_config_path()
        if project_path and project_path.exists():
            project_path.unlink()
        return project_path or (Path.cwd() / _PROJECT_CONFIG_NAME)


# ---------------------------------------------------------------------------
# Dict helpers
# ---------------------------------------------------------------------------


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict to dotted-key form."""
    flat: dict[str, Any] = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            flat.update(_flatten(v, full_key))
        else:
            flat[full_key] = v
    return flat


def _set_nested_dict(d: dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set a value in a nested dict using a dotted key."""
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = _coerce_value(value)


def _coerce_value(value: Any) -> Any:
    """Best-effort coercion of string values from CLI to appropriate types."""
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.lower() in ("true", "yes", "on"):
            return True
        if s.lower() in ("false", "no", "off"):
            return False
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
    return value


__all__ = [
    "load_global_config",
    "load_project_config",
    "load_proxy_defaults",
    "load_copium_config",
    "get_config_sources",
    "show_merged_flat",
    "set_config_value",
    "reset_config",
    "find_project_config_path",
    "_GLOBAL_CONFIG_PATH",
]
