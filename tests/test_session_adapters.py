"""Tests for session archive adapters (Claude Code, Cursor, Aider, OpenCode)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


class TestClaudeCodeAdapter:
    def test_detect_claude_code_format(self):
        from copium.session.adapters.claude_code import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "human", "message": {"role": "user", "content": "hello"}}) + "
")
            path = Path(f.name)
        assert adapter.detect(path)
        path.unlink()

    def test_parse_basic_session(self):
        from copium.session.adapters.claude_code import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "human", "message": {"role": "user", "content": "Fix bug"}}) + "
")
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "Fixed."}}) + "
")
            path = Path(f.name)
        messages = adapter.parse(path)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"
        path.unlink()

    def test_roundtrip(self):
        from copium.session.adapters.claude_code import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "human", "message": {"role": "user", "content": "hello"}}) + "
")
            path = Path(f.name)
        messages = adapter.parse(path)
        out_path = Path(f.name + "_out.jsonl")
        adapter.write(messages, out_path)
        messages2 = adapter.parse(out_path)
        assert len(messages2) == len(messages)
        path.unlink()
        out_path.unlink()


class TestCursorAdapter:
    def test_detect_cursor_format(self):
        from copium.session.adapters.cursor import CursorAdapter
        adapter = CursorAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"composerId": "abc", "messages": [{"role": "user", "content": "hi"}]}, f)
            path = Path(f.name)
        assert adapter.detect(path)
        path.unlink()

    def test_parse_cursor_session(self):
        from copium.session.adapters.cursor import CursorAdapter
        adapter = CursorAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"composerId": "abc", "messages": [
                {"role": "user", "content": "What does this do?"},
                {"role": "assistant", "content": "It parses."},
            ]}, f)
            path = Path(f.name)
        messages = adapter.parse(path)
        assert len(messages) == 2
        assert messages[0].content == "What does this do?"
        path.unlink()


class TestAiderAdapter:
    def test_detect_aider_jsonl(self):
        from copium.session.adapters.aider import AiderAdapter
        adapter = AiderAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", dir="/tmp", prefix="aider_", delete=False) as f:
            f.write(json.dumps({"role": "user", "content": "fix"}) + "
")
            path = Path(f.name)
        assert adapter.detect(path)
        path.unlink()

    def test_parse_aider_markdown(self):
        from copium.session.adapters.aider import AiderAdapter
        adapter = AiderAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".aider.chat.history.md", delete=False) as f:
            f.write("#### user
Fix the bug

#### assistant
Fixed it.
")
            path = Path(f.name)
        messages = adapter.parse(path)
        assert len(messages) == 2
        assert messages[0].role == "user"
        path.unlink()


class TestOpenCodeAdapter:
    def test_detect_opencode(self):
        from copium.session.adapters.opencode import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir="/tmp", prefix="opencode_", delete=False) as f:
            json.dump({"session": {"messages": [{"role": "user", "content": "hi"}]}, "provider": "anthropic"}, f)
            path = Path(f.name)
        assert adapter.detect(path)
        path.unlink()

    def test_parse_opencode(self):
        from copium.session.adapters.opencode import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir="/tmp", prefix="opencode_", delete=False) as f:
            json.dump({"session": {"messages": [
                {"role": "user", "content": "help"},
                {"role": "assistant", "content": "sure"},
            ]}, "provider": "openai"}, f)
            path = Path(f.name)
        messages = adapter.parse(path)
        assert len(messages) == 2
        path.unlink()


class TestAdapterRegistry:
    def test_list_adapters(self):
        from copium.session.adapters import list_adapters
        adapters = list_adapters()
        assert "claude_code" in adapters
        assert "cursor" in adapters
        assert "aider" in adapters
        assert "opencode" in adapters

    def test_detect_adapter_claude(self):
        from copium.session.adapters import detect_adapter
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "human", "message": {"role": "user", "content": "hi"}}) + "
")
            path = Path(f.name)
        adapter = detect_adapter(path)
        assert adapter is not None
        assert adapter.name == "claude_code"
        path.unlink()
