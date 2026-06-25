"""Tests for _register_copium_hooks function."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copium.cli import wrap as wrap_mod


class TestRegisterCopiumHooks:
    """Tests for _register_copium_hooks function."""

    @pytest.fixture
    def mock_claude_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Mock the settings path to a temp file under .claude directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return settings_path

    def test_adds_compress_read_hook(self, mock_claude_dir: Path):
        """Register adds compress-read hook for Read tool."""
        initial = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "rtk-rewrite"}]
                    }
                ]
            }
        }
        mock_claude_dir.write_text(json.dumps(initial))

        wrap_mod._register_copium_hooks(verbose=False)

        with mock_claude_dir.open() as f:
            result = json.load(f)

        hooks = result["hooks"]["PreToolUse"]
        read_hooks = [h for h in hooks if h.get("matcher") == "Read"]
        assert len(read_hooks) == 1
        assert read_hooks[0]["hooks"][0]["command"] == "copium compress-read --max-lines 200"

    def test_adds_compress_search_hook(self, mock_claude_dir: Path):
        """Register adds compress-search hook for Grep tool."""
        initial = {"hooks": {"PreToolUse": []}}
        mock_claude_dir.write_text(json.dumps(initial))

        wrap_mod._register_copium_hooks(verbose=False)

        with mock_claude_dir.open() as f:
            result = json.load(f)

        hooks = result["hooks"]["PreToolUse"]
        grep_hooks = [h for h in hooks if h.get("matcher") == "Grep"]
        assert len(grep_hooks) == 1
        assert grep_hooks[0]["hooks"][0]["command"] == "copium compress-search --max-results 50"

    def test_idempotent_does_not_duplicate(self, mock_claude_dir: Path):
        """Running twice does not create duplicate hooks."""
        initial = {"hooks": {"PreToolUse": []}}
        mock_claude_dir.write_text(json.dumps(initial))

        wrap_mod._register_copium_hooks(verbose=False)
        wrap_mod._register_copium_hooks(verbose=False)

        with mock_claude_dir.open() as f:
            result = json.load(f)

        hooks = result["hooks"]["PreToolUse"]
        read_hooks = [h for h in hooks if h.get("matcher") == "Read"]
        grep_hooks = [h for h in hooks if h.get("matcher") == "Grep"]
        assert len(read_hooks) == 1
        assert len(grep_hooks) == 1

    def test_preserves_existing_hooks(self, mock_claude_dir: Path):
        """Existing hooks are preserved."""
        initial = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "rtk-rewrite"}]
                    }
                ]
            }
        }
        mock_claude_dir.write_text(json.dumps(initial))

        wrap_mod._register_copium_hooks(verbose=False)

        with mock_claude_dir.open() as f:
            result = json.load(f)

        hooks = result["hooks"]["PreToolUse"]
        bash_hooks = [h for h in hooks if h.get("matcher") == "Bash"]
        assert len(bash_hooks) == 1
        assert bash_hooks[0]["hooks"][0]["command"] == "rtk-rewrite"

    def test_handles_missing_settings_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Does not crash when settings file doesn't exist."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # No settings.json file exists
        wrap_mod._register_copium_hooks(verbose=False)  # Should not raise

    def test_handles_malformed_json(self, mock_claude_dir: Path):
        """Does not crash on malformed JSON."""
        mock_claude_dir.write_text("{not valid json")
        wrap_mod._register_copium_hooks(verbose=False)  # Should not raise

    def test_handles_non_dict_hooks(self, mock_claude_dir: Path):
        """Handles when hooks is not a dict."""
        mock_claude_dir.write_text(json.dumps({"hooks": "not a dict"}))
        wrap_mod._register_copium_hooks(verbose=False)  # Should not raise

    def test_handles_non_list_pre_use(self, mock_claude_dir: Path):
        """Handles when PreToolUse is not a list."""
        mock_claude_dir.write_text(json.dumps({"hooks": {"PreToolUse": "not a list"}}))
        wrap_mod._register_copium_hooks(verbose=False)  # Should not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])