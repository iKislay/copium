"""Tests for the Claude settings guard (copium.claude_settings).

Covers the destructive-overwrite bug class: user-owned config in
``~/.claude/settings.json`` (custom ANTHROPIC_BASE_URL endpoints, plugins,
MCP servers) must survive wrap/unwrap round-trips and external tool writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copium.claude_settings import (
    backup_settings_once,
    is_copium_proxy_url,
    pop_env_original,
    record_env_original,
    restore_deleted_keys,
)


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPIUM_WORKSPACE_DIR", str(tmp_path / ".copium"))


class TestIsCopiumProxyUrl:
    def test_loopback_urls_are_copium(self) -> None:
        assert is_copium_proxy_url("http://127.0.0.1:8787")
        assert is_copium_proxy_url("http://localhost:9999")
        assert is_copium_proxy_url("http://127.0.0.1:8787/")
        assert is_copium_proxy_url("https://127.0.0.1:8787/v1")

    def test_user_endpoints_are_not_copium(self) -> None:
        assert not is_copium_proxy_url("https://cc.freemodel.dev")
        assert not is_copium_proxy_url("https://openrouter.ai/api")
        assert not is_copium_proxy_url("https://api.anthropic.com")
        assert not is_copium_proxy_url(None)
        assert not is_copium_proxy_url(8787)
        assert not is_copium_proxy_url("")


class TestEnvLedger:
    def test_round_trip(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        record_env_original(settings, "ANTHROPIC_BASE_URL", "https://cc.freemodel.dev")
        recorded, original = pop_env_original(settings, "ANTHROPIC_BASE_URL")
        assert recorded is True
        assert original == "https://cc.freemodel.dev"
        # Entry consumed
        recorded, _ = pop_env_original(settings, "ANTHROPIC_BASE_URL")
        assert recorded is False

    def test_first_record_wins(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        record_env_original(settings, "ANTHROPIC_BASE_URL", "https://cc.freemodel.dev")
        record_env_original(settings, "ANTHROPIC_BASE_URL", "http://127.0.0.1:8787")
        _, original = pop_env_original(settings, "ANTHROPIC_BASE_URL")
        assert original == "https://cc.freemodel.dev"

    def test_none_means_key_was_absent(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        record_env_original(settings, "ENABLE_TOOL_SEARCH", None)
        recorded, original = pop_env_original(settings, "ENABLE_TOOL_SEARCH")
        assert recorded is True
        assert original is None

    def test_ledger_is_per_settings_path(self, tmp_path: Path) -> None:
        record_env_original(tmp_path / "a.json", "K", "va")
        recorded, _ = pop_env_original(tmp_path / "b.json", "K")
        assert recorded is False


class TestBackupOnce:
    def test_creates_backup_and_never_overwrites(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text('{"env": {"A": "1"}}', encoding="utf-8")
        backup = backup_settings_once(settings)
        assert backup is not None and backup.exists()
        assert backup.read_text() == '{"env": {"A": "1"}}'

        settings.write_text('{"env": {"A": "2"}}', encoding="utf-8")
        assert backup_settings_once(settings) is None
        assert backup.read_text() == '{"env": {"A": "1"}}'  # pre-Copium state kept

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        assert backup_settings_once(tmp_path / "nope.json") is None


class TestRestoreDeletedKeys:
    def test_restores_dropped_env_key(self) -> None:
        before = {
            "env": {
                "ANTHROPIC_API_KEY": "fe_oa_x",
                "ANTHROPIC_BASE_URL": "https://cc.freemodel.dev",
            },
            "apiKeyHelper": "/bin/helper",
        }
        after = {"env": {"ANTHROPIC_API_KEY": "fe_oa_x"}, "hooks": {"PreToolUse": []}}
        restored = restore_deleted_keys(before, after)
        assert "env.ANTHROPIC_BASE_URL" in restored
        assert "apiKeyHelper" in restored
        assert after["env"]["ANTHROPIC_BASE_URL"] == "https://cc.freemodel.dev"
        assert after["apiKeyHelper"] == "/bin/helper"
        # Additions from the external write are kept.
        assert after["hooks"] == {"PreToolUse": []}

    def test_keeps_changed_values(self) -> None:
        before = {"env": {"K": "old"}}
        after = {"env": {"K": "new"}}
        assert restore_deleted_keys(before, after) == []
        assert after["env"]["K"] == "new"

    def test_noop_when_nothing_deleted(self) -> None:
        before = {"a": 1}
        after = {"a": 1, "b": 2}
        assert restore_deleted_keys(before, after) == []


class TestRtkInitGuard:
    def test_restores_keys_deleted_by_external_rtk_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from copium.rtk import installer

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        original = {
            "env": {
                "ANTHROPIC_API_KEY": "fe_oa_x",
                "ANTHROPIC_BASE_URL": "https://cc.freemodel.dev",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
            "enabledPlugins": {"playwright@marketplace": True},
        }
        settings.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

        def fake_rtk_init(*args, **kwargs):
            # Simulate a templated overwrite: drops BASE_URL + plugins.
            settings.write_text(
                json.dumps(
                    {
                        "env": {"ANTHROPIC_API_KEY": "fe_oa_x"},
                        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]},
                    }
                ),
                encoding="utf-8",
            )

            class R:
                returncode = 0
                stderr = ""

            return R()

        monkeypatch.setattr(installer.subprocess, "run", fake_rtk_init)

        assert installer.register_claude_hooks(Path("/fake/rtk")) is True

        payload = json.loads(settings.read_text(encoding="utf-8"))
        # Deleted user keys restored
        assert payload["env"]["ANTHROPIC_BASE_URL"] == "https://cc.freemodel.dev"
        assert payload["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
        assert payload["enabledPlugins"] == {"playwright@marketplace": True}
        # rtk's own additions kept
        assert payload["hooks"]["PreToolUse"] == [{"matcher": "Bash", "hooks": []}]
        # One-time pre-modification backup exists
        assert (claude_dir / "settings.json.copium-backup").exists()

    def test_restores_file_corrupted_by_external_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from copium.rtk import installer

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        original = {"env": {"ANTHROPIC_BASE_URL": "https://cc.freemodel.dev"}}
        settings.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

        def fake_rtk_init(*args, **kwargs):
            settings.write_text("{not json", encoding="utf-8")

            class R:
                returncode = 0
                stderr = ""

            return R()

        monkeypatch.setattr(installer.subprocess, "run", fake_rtk_init)
        installer.register_claude_hooks(Path("/fake/rtk"))

        assert json.loads(settings.read_text(encoding="utf-8")) == original
