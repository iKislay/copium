"""Tests for session CLI commands (smoke tests)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from copium.cli.main import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_session(tmp_path):
    import json
    path = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"type": "human", "message": {"role": "user", "content": "hello"}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "hi there"}}),
        json.dumps({"type": "tool_result", "message": {"role": "tool", "content": "file contents " * 50}}),
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


class TestSessionCLI:
    def test_compact(self, runner, sample_session, tmp_path):
        output_path = tmp_path / "compacted.jsonl"
        result = runner.invoke(main, ["session", "compact", str(sample_session), "-o", str(output_path)])
        assert result.exit_code == 0
        assert "Compacted" in result.output
        assert output_path.exists()

    def test_compact_json_output(self, runner, sample_session):
        result = runner.invoke(main, ["session", "compact", str(sample_session), "--json-output"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "savings_pct" in data

    def test_summary(self, runner, sample_session):
        result = runner.invoke(main, ["session", "summary", str(sample_session)])
        assert result.exit_code == 0
        assert "Messages:" in result.output

    def test_expand(self, runner, sample_session, tmp_path):
        # First compact
        compacted = tmp_path / "compacted.jsonl"
        runner.invoke(main, ["session", "compact", str(sample_session), "-o", str(compacted)])
        # Then expand
        expanded = tmp_path / "expanded.jsonl"
        result = runner.invoke(main, ["session", "expand", str(compacted), "-o", str(expanded)])
        assert result.exit_code == 0
        assert expanded.exists()

    def test_apply(self, runner, sample_session):
        result = runner.invoke(main, ["session", "apply", str(sample_session), "What happened?"])
        assert result.exit_code == 0
        # Should output JSON
        import json
        messages = json.loads(result.output)
        assert isinstance(messages, list)
        assert len(messages) > 0

    def test_adapters(self, runner):
        result = runner.invoke(main, ["session", "adapters"])
        assert result.exit_code == 0
        assert "claude_code" in result.output
        assert "cursor" in result.output
        assert "aider" in result.output
        assert "opencode" in result.output

    def test_diff(self, runner, sample_session, tmp_path):
        # Compact to create a second file
        compacted = tmp_path / "compacted.jsonl"
        runner.invoke(main, ["session", "compact", str(sample_session), "-o", str(compacted)])
        # Diff them
        result = runner.invoke(main, ["session", "diff", str(sample_session), str(compacted)])
        assert result.exit_code == 0
        assert "Delta:" in result.output

    def test_replay_dry_run(self, runner, sample_session):
        result = runner.invoke(main, ["session", "replay", str(sample_session), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.output
