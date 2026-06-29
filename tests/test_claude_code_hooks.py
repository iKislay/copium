"""Tests for Claude Code hook integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copium.hooks.claude_code import (
    ClaudeCodeHookConfig,
    generate_hook_settings,
    write_hook_settings,
)


@pytest.fixture
def hook_config(tmp_path):
    return ClaudeCodeHookConfig(
        settings_dir=tmp_path / ".claude",
        hooks_dir=tmp_path / ".copium" / "hooks",
        checkpoint_dir=tmp_path / ".copium" / "checkpoints",
    )


class TestGenerateHookSettings:
    """Tests for generate_hook_settings."""

    def test_generates_valid_settings(self, hook_config):
        settings = generate_hook_settings(hook_config)

        assert "hooks" in settings
        assert "PreCompact" in settings["hooks"]
        assert "PostCompact" in settings["hooks"]

    def test_precompact_hook_has_command(self, hook_config):
        settings = generate_hook_settings(hook_config)
        pre_hooks = settings["hooks"]["PreCompact"]

        assert len(pre_hooks) == 1
        assert "copium.hooks.claude_code" in pre_hooks[0]["command"]
        assert "capture" in pre_hooks[0]["command"]

    def test_postcompact_hook_has_command(self, hook_config):
        settings = generate_hook_settings(hook_config)
        post_hooks = settings["hooks"]["PostCompact"]

        assert len(post_hooks) == 1
        assert "copium.hooks.claude_code" in post_hooks[0]["command"]
        assert "recover" in post_hooks[0]["command"]

    def test_hooks_have_timeout(self, hook_config):
        settings = generate_hook_settings(hook_config)

        for hook_list in settings["hooks"].values():
            for hook in hook_list:
                assert "timeout" in hook
                assert hook["timeout"] > 0

    def test_hooks_have_description(self, hook_config):
        settings = generate_hook_settings(hook_config)

        for hook_list in settings["hooks"].values():
            for hook in hook_list:
                assert "description" in hook
                assert "Copium" in hook["description"]


class TestWriteHookSettings:
    """Tests for write_hook_settings."""

    def test_creates_settings_file(self, hook_config):
        path = write_hook_settings(hook_config)

        assert path.exists()
        data = json.loads(path.read_text())
        assert "hooks" in data

    def test_merges_with_existing(self, hook_config):
        # Create existing settings
        hook_config.settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = hook_config.settings_dir / "settings.json"
        existing = {
            "theme": "dark",
            "hooks": {
                "PreToolUse": [{"command": "echo pre", "description": "Pre tool"}],
            },
        }
        settings_file.write_text(json.dumps(existing))

        # Write hook settings with merge
        write_hook_settings(hook_config, merge=True)

        data = json.loads(settings_file.read_text())
        # Original settings preserved
        assert data["theme"] == "dark"
        assert "PreToolUse" in data["hooks"]
        # Copium hooks added
        assert "PreCompact" in data["hooks"]
        assert "PostCompact" in data["hooks"]

    def test_removes_old_copium_hooks_on_merge(self, hook_config):
        # Create existing settings with old Copium hooks
        hook_config.settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = hook_config.settings_dir / "settings.json"
        existing = {
            "hooks": {
                "PreCompact": [
                    {"command": "python -m copium.hooks.claude_code capture --old", "description": "Old"},
                    {"command": "echo custom", "description": "Custom hook"},
                ],
            },
        }
        settings_file.write_text(json.dumps(existing))

        write_hook_settings(hook_config, merge=True)

        data = json.loads(settings_file.read_text())
        pre_hooks = data["hooks"]["PreCompact"]
        # Old copium hook removed, custom hook preserved, new copium hook added
        commands = [h["command"] for h in pre_hooks]
        assert "echo custom" in commands
        assert any("copium" in c for c in commands)
        assert "--old" not in str(commands)

    def test_overwrite_mode(self, hook_config):
        # Create existing settings
        hook_config.settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = hook_config.settings_dir / "settings.json"
        existing = {"hooks": {"CustomEvent": [{"command": "echo hi"}]}}
        settings_file.write_text(json.dumps(existing))

        write_hook_settings(hook_config, merge=False)

        data = json.loads(settings_file.read_text())
        # Only Copium hooks remain
        assert "PreCompact" in data["hooks"]
        assert "PostCompact" in data["hooks"]

    def test_creates_hooks_directory(self, hook_config):
        generate_hook_settings(hook_config)
        assert hook_config.hooks_dir.exists()

    def test_handles_corrupt_existing_settings(self, hook_config):
        hook_config.settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = hook_config.settings_dir / "settings.json"
        settings_file.write_text("not valid json{{{")

        # Should not raise, should overwrite
        path = write_hook_settings(hook_config, merge=True)
        data = json.loads(path.read_text())
        assert "hooks" in data
