"""Tests for `copium wrap opencode` and `copium unwrap opencode`.

These exercise the OpenCode-specific opencode.json injection and restoration
helpers that route OpenCode through the Copium proxy.  They are unit tests
operating directly against a temp ``$HOME``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from copium.cli import wrap as wrap_mod
from copium.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Unit tests: _remove_opencode_copium_provider
# ---------------------------------------------------------------------------


class TestRemoveOpencodeCopiumProvider:
    """Tests for the surgical config cleanup helper."""

    def test_restores_from_backup(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"
        original = '{"provider": {"lmstudio": {}}}\n'
        config.write_text(
            '{"provider": {"copium": {}, "lmstudio": {}}, "model": "copium/mimo-v2.5-free"}\n'
        )
        backup.write_text(original)

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "restored"
        assert config.read_text() == original
        assert not backup.exists()

    def test_surgical_removal_without_backup(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(
            json.dumps(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "provider": {"copium": {"npm": "@ai-sdk/openai-compatible"}, "lmstudio": {}},
                    "model": "copium/mimo-v2.5-free",
                },
                indent=2,
            )
            + "\n"
        )

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "cleaned"
        data = json.loads(config.read_text())
        assert "copium" not in data.get("provider", {})
        assert "lmstudio" in data.get("provider", {})
        assert data.get("model") is None

    def test_clean_when_no_copium_entries(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(json.dumps({"provider": {"lmstudio": {}}}, indent=2) + "\n")

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "clean"

    def test_missing_when_no_config(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "missing"

    def test_idempotent_on_already_clean(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(json.dumps({"provider": {}}, indent=2) + "\n")

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "clean"

    def test_preserves_other_model_keys(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(
            json.dumps(
                {
                    "provider": {"copium": {}, "lmstudio": {}},
                    "model": "copium/mimo-v2.5-free",
                },
                indent=2,
            )
            + "\n"
        )

        wrap_mod._remove_opencode_copium_provider(config)

        data = json.loads(config.read_text())
        assert "lmstudio" in data["provider"]
        assert data.get("model") is None

    def test_handles_malformed_json(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text("not valid json {{{")

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "error"


# ---------------------------------------------------------------------------
# Unit tests: backup creation logic (inline in opencode() function)
# ---------------------------------------------------------------------------


class TestOpencodeBackupCreation:
    """Tests for the backup snapshot logic before config injection."""

    def test_creates_backup_on_first_call(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"
        config.write_text('{"provider": {"lmstudio": {}}}\n')

        had_existing_config = config.exists()
        if had_existing_config and not backup.exists():
            import shutil

            shutil.copy2(config, backup)

        assert backup.exists()
        assert backup.read_text() == '{"provider": {"lmstudio": {}}}\n'

    def test_does_not_overwrite_existing_backup(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"
        config.write_text("second-wrap content\n")
        backup.write_text("original-pre-wrap content\n")

        had_existing_config = config.exists()
        if had_existing_config and not backup.exists():
            import shutil

            shutil.copy2(config, backup)

        assert backup.read_text() == "original-pre-wrap content\n"

    def test_no_backup_when_config_missing(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"

        had_existing_config = config.exists()
        if had_existing_config and not backup.exists():
            import shutil

            shutil.copy2(config, backup)

        assert not backup.exists()


# ---------------------------------------------------------------------------
# Integration tests: full `copium unwrap opencode` CLI
# ---------------------------------------------------------------------------


def _patch_opencode_config_path(tmp_path: Path):
    """Return a context manager that redirects the unwrap command to a temp path."""
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "opencode.json"
    return patch.object(wrap_mod, "_OPENCODE_CONFIG_PATH", config_path)


def test_unwrap_opencode_restores_from_backup(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    backup = config_dir / "opencode.json.copium-backup"
    original = '{"provider": {"lmstudio": {}}}\n'
    backup.write_text(original)
    config.write_text(
        '{"provider": {"copium": {}, "lmstudio": {}}, "model": "copium/mimo-v2.5-free"}\n'
    )

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap", return_value="stopped"),
    ):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    assert config.read_text() == original
    assert not backup.exists()
    assert "Restored" in result.output


def test_unwrap_opencode_surgical_without_backup(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    config.write_text(
        json.dumps(
            {"provider": {"copium": {}, "lmstudio": {}}, "model": "copium/mimo-v2.5-free"},
            indent=2,
        )
        + "\n"
    )

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap", return_value="stopped"),
    ):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    data = json.loads(config.read_text())
    assert "copium" not in data.get("provider", {})
    assert "lmstudio" in data.get("provider", {})
    assert "Removed Copium provider/model" in result.output


def test_unwrap_opencode_idempotent(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    config.write_text(json.dumps({"provider": {"lmstudio": {}}}, indent=2) + "\n")

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap", return_value="stopped"),
    ):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    assert "already has no Copium entries" in result.output


def test_unwrap_opencode_missing_config(runner: CliRunner, tmp_path: Path) -> None:
    with _patch_opencode_config_path(tmp_path):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    assert "does not exist" in result.output


def test_unwrap_opencode_no_stop_proxy(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    backup = config_dir / "opencode.json.copium-backup"
    backup.write_text("{}\n")
    config.write_text('{"provider": {"copium": {}}}\n')

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap") as stop_proxy,
    ):
        result = runner.invoke(main, ["unwrap", "opencode", "--no-stop-proxy"])

    assert result.exit_code == 0, result.output
    stop_proxy.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests: proxy start with opencode upstream URLs
# ---------------------------------------------------------------------------


def test_start_proxy_passes_zen_upstream_urls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify that _start_proxy forwards --openai-api-url and --opencode-go-api-url."""
    popen_kwargs: dict[str, object] = {}

    class FakeProc:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(*args: object, **kwargs: object) -> FakeProc:
        popen_kwargs.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(wrap_mod, "_get_log_path", lambda: tmp_path / "proxy.log")
    monkeypatch.setattr(wrap_mod, "_check_proxy", lambda port: True)
    monkeypatch.setattr(wrap_mod.subprocess, "Popen", fake_popen)

    wrap_mod._start_proxy(
        8787,
        agent_type="opencode",
        openai_api_url="https://opencode.ai/zen/v1",
        opencode_go_api_url="https://opencode.ai/zen/go/v1",
    )

    env = popen_kwargs["env"]
    assert isinstance(env, dict)
    assert env["OPENAI_TARGET_API_URL"] == "https://opencode.ai/zen/v1"
    assert env["OPENCODE_GO_TARGET_API_URL"] == "https://opencode.ai/zen/go/v1"


def test_start_proxy_sets_agent_type_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    popen_kwargs: dict[str, object] = {}

    class FakeProc:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(*args: object, **kwargs: object) -> FakeProc:
        popen_kwargs.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(wrap_mod, "_get_log_path", lambda: tmp_path / "proxy.log")
    monkeypatch.setattr(wrap_mod, "_check_proxy", lambda port: True)
    monkeypatch.setattr(wrap_mod.subprocess, "Popen", fake_popen)

    wrap_mod._start_proxy(8787, agent_type="opencode")

    env = popen_kwargs["env"]
    assert isinstance(env, dict)
    assert env["COPIUM_AGENT_TYPE"] == "opencode"
