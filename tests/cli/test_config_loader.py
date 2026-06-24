"""Tests for copium.config_loader — global/project config hierarchy."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from copium.config_loader import (
    _coerce_value,
    _deep_merge,
    _flatten,
    _set_nested_dict,
    find_project_config_path,
    load_copium_config,
    load_global_config,
    load_project_config,
    load_proxy_defaults,
    reset_config,
    set_config_value,
    show_merged_flat,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def global_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect global config dir to a temp directory."""
    config_dir = tmp_path / ".copium"
    config_dir.mkdir()
    monkeypatch.setattr(
        "copium.config_loader._GLOBAL_CONFIG_DIR", config_dir
    )
    monkeypatch.setattr(
        "copium.config_loader._GLOBAL_CONFIG_PATH", config_dir / "config.toml"
    )
    return config_dir


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp project directory and chdir into it."""
    project = tmp_path / "myproject"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_merge_flat(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_nested(self) -> None:
        base = {"proxy": {"port": 8787, "host": "127.0.0.1"}}
        override = {"proxy": {"port": 9090}}
        result = _deep_merge(base, override)
        assert result == {"proxy": {"port": 9090, "host": "127.0.0.1"}}

    def test_merge_deeply_nested(self) -> None:
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 10}}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": {"c": 10, "d": 2}}}

    def test_merge_override_type_change(self) -> None:
        base = {"a": 1}
        override = {"a": "string"}
        result = _deep_merge(base, override)
        assert result == {"a": "string"}


# ---------------------------------------------------------------------------
# Flatten / unflatten
# ---------------------------------------------------------------------------


class TestFlatten:
    def test_flat_dict(self) -> None:
        assert _flatten({"a": 1}) == {"a": 1}

    def test_nested_dict(self) -> None:
        d = {"proxy": {"port": 8787, "host": "127.0.0.1"}}
        assert _flatten(d) == {"proxy.port": 8787, "proxy.host": "127.0.0.1"}

    def test_deeply_nested(self) -> None:
        d = {"a": {"b": {"c": 42}}}
        assert _flatten(d) == {"a.b.c": 42}

    def test_empty(self) -> None:
        assert _flatten({}) == {}


class TestSetNestedDict:
    def test_simple(self) -> None:
        d: dict[str, Any] = {}
        _set_nested_dict(d, "proxy.port", 8787)
        assert d == {"proxy": {"port": 8787}}

    def test_existing(self) -> None:
        d: dict[str, Any] = {"proxy": {"host": "127.0.0.1"}}
        _set_nested_dict(d, "proxy.port", 8787)
        assert d == {"proxy": {"host": "127.0.0.1", "port": 8787}}

    def test_override(self) -> None:
        d: dict[str, Any] = {"proxy": {"port": 8787}}
        _set_nested_dict(d, "proxy.port", 9090)
        assert d == {"proxy": {"port": 9090}}


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------


class TestCoerceValue:
    def test_bool_true(self) -> None:
        assert _coerce_value("true") is True
        assert _coerce_value("yes") is True
        assert _coerce_value("on") is True

    def test_bool_false(self) -> None:
        assert _coerce_value("false") is False
        assert _coerce_value("no") is False
        assert _coerce_value("off") is False

    def test_int(self) -> None:
        assert _coerce_value("42") == 42

    def test_float(self) -> None:
        assert _coerce_value("3.14") == 3.14

    def test_passthrough(self) -> None:
        assert _coerce_value("hello") == "hello"
        assert _coerce_value(42) == 42
        assert _coerce_value(True) is True


# ---------------------------------------------------------------------------
# Global config loading
# ---------------------------------------------------------------------------


class TestLoadGlobalConfig:
    def test_missing_file(self, global_config_dir: Path) -> None:
        assert load_global_config() == {}

    def test_valid_toml(self, global_config_dir: Path) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text(
            textwrap.dedent("""\
                [proxy]
                port = 9000
                host = "127.0.0.1"

                [compression]
                preset = "aggressive"
            """)
        )
        result = load_global_config()
        assert result["proxy"]["port"] == 9000
        assert result["compression"]["preset"] == "aggressive"

    def test_invalid_toml(self, global_config_dir: Path, caplog: Any) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text("this is not valid toml {{{")
        result = load_global_config()
        assert result == {}
        assert "Failed to parse" in caplog.text


# ---------------------------------------------------------------------------
# Project config loading
# ---------------------------------------------------------------------------


class TestLoadProjectConfig:
    def test_no_project_config(self, project_dir: Path) -> None:
        assert load_project_config() == {}

    def test_valid_json(self, project_dir: Path) -> None:
        config_file = project_dir / "copium.json"
        config_file.write_text(json.dumps({"proxy": {"port": 9999}}))
        result = load_project_config()
        assert result["proxy"]["port"] == 9999

    def test_invalid_json(self, project_dir: Path, caplog: Any) -> None:
        config_file = project_dir / "copium.json"
        config_file.write_text("{invalid json")
        result = load_project_config()
        assert result == {}
        assert "Failed to parse" in caplog.text

    def test_searches_parent(self, project_dir: Path) -> None:
        config_file = project_dir / "copium.json"
        config_file.write_text(json.dumps({"proxy": {"port": 7777}}))
        subdir = project_dir / "src" / "lib"
        subdir.mkdir(parents=True)
        import os

        os.chdir(subdir)
        result = load_project_config()
        assert result["proxy"]["port"] == 7777

    def test_stops_at_git_boundary(self, project_dir: Path) -> None:
        # Create a git boundary
        (project_dir / ".git").mkdir()
        # Config at parent should NOT be found from inside the project
        parent_config = project_dir.parent / "copium.json"
        parent_config.write_text(json.dumps({"proxy": {"port": 1111}}))
        subdir = project_dir / "src"
        subdir.mkdir()
        import os

        os.chdir(subdir)
        result = load_project_config()
        assert result == {}


class TestFindProjectConfigPath:
    def test_found(self, project_dir: Path) -> None:
        config_file = project_dir / "copium.json"
        config_file.write_text("{}")
        assert find_project_config_path() == config_file

    def test_not_found(self, project_dir: Path) -> None:
        assert find_project_config_path() is None


# ---------------------------------------------------------------------------
# Proxy defaults (merged flat)
# ---------------------------------------------------------------------------


class TestLoadProxyDefaults:
    def test_empty_when_no_files(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        result = load_proxy_defaults()
        assert result == {}

    def test_global_only(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text(
            textwrap.dedent("""\
                [proxy]
                port = 9000
            """)
        )
        result = load_proxy_defaults()
        assert result["proxy.port"] == 9000

    def test_project_overrides_global(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        global_file = global_config_dir / "config.toml"
        global_file.write_text(
            textwrap.dedent("""\
                [proxy]
                port = 9000
            """)
        )
        project_file = project_dir / "copium.json"
        project_file.write_text(json.dumps({"proxy": {"port": 7777}}))
        result = load_proxy_defaults()
        assert result["proxy.port"] == 7777


# ---------------------------------------------------------------------------
# CopiumConfig construction
# ---------------------------------------------------------------------------


class TestLoadCopiumConfig:
    def test_defaults(self, global_config_dir: Path, project_dir: Path) -> None:
        config = load_copium_config()
        # Default SmartCrusher max_items
        assert config.smart_crusher.max_items_after_crush == 15

    def test_preset_override(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        config = load_copium_config(preset="aggressive")
        assert config.smart_crusher.max_items_after_crush == 10

    def test_config_file_preset(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text(
            textwrap.dedent("""\
                [compression]
                preset = "aggressive"
            """)
        )
        config = load_copium_config()
        assert config.smart_crusher.max_items_after_crush == 10

    def test_cli_preset_overrides_config(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text(
            textwrap.dedent("""\
                [compression]
                preset = "minimal"
            """)
        )
        # CLI preset should override config file preset
        config = load_copium_config(preset="aggressive")
        assert config.smart_crusher.max_items_after_crush == 10

    def test_explicit_overrides(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        config = load_copium_config(
            overrides={"compression.quality_gate": False}
        )
        assert config.quality_gate.enabled is False


# ---------------------------------------------------------------------------
# set_config_value / reset_config
# ---------------------------------------------------------------------------


class TestSetConfigValue:
    def test_set_global(
        self, global_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = set_config_value("proxy.port", "9090", global_scope=True)
        assert path.exists()
        result = load_global_config()
        assert result["proxy"]["port"] == 9090

    def test_set_project(self, project_dir: Path) -> None:
        path = set_config_value("proxy.port", "9090", global_scope=False)
        assert path.exists()
        result = json.loads(path.read_text())
        assert result["proxy"]["port"] == 9090

    def test_shorthand_key(self, project_dir: Path) -> None:
        set_config_value("port", "9090", global_scope=False)
        path = project_dir / "copium.json"
        result = json.loads(path.read_text())
        assert result["proxy"]["port"] == 9090

    def test_coercion(self, project_dir: Path) -> None:
        set_config_value("telemetry.enabled", "true", global_scope=False)
        path = project_dir / "copium.json"
        result = json.loads(path.read_text())
        assert result["telemetry"]["enabled"] is True


class TestResetConfig:
    def test_reset_global(
        self, global_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text("[proxy]\nport = 9000\n")
        reset_config(global_scope=True)
        assert not config_file.exists()

    def test_reset_project(self, project_dir: Path) -> None:
        config_file = project_dir / "copium.json"
        config_file.write_text("{}")
        reset_config(global_scope=False)
        assert not config_file.exists()


# ---------------------------------------------------------------------------
# show_merged_flat
# ---------------------------------------------------------------------------


class TestShowMergedFlat:
    def test_global_only(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text(
            textwrap.dedent("""\
                [proxy]
                port = 9000
            """)
        )
        result = show_merged_flat(global_only=True)
        assert result == {"proxy.port": 9000}

    def test_merged(
        self, global_config_dir: Path, project_dir: Path
    ) -> None:
        config_file = global_config_dir / "config.toml"
        config_file.write_text(
            textwrap.dedent("""\
                [proxy]
                port = 9000
                host = "127.0.0.1"
            """)
        )
        project_file = project_dir / "copium.json"
        project_file.write_text(json.dumps({"proxy": {"port": 7777}}))
        result = show_merged_flat()
        assert result["proxy.port"] == 7777
        assert result["proxy.host"] == "127.0.0.1"
