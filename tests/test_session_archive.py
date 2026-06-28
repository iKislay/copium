"""Tests for session archive and compactor."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from copium.session.archive import CompactConfig, SessionArchive, SessionMessage
from copium.session.compactor import SessionCompactor
from copium.session.applicator import SessionApplicator
from copium.session.expander import SessionExpander


class TestSessionArchive:
    def test_parse_jsonl(self, tmp_path):
        path = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "human", "message": {"role": "user", "content": "hello"}}),
            json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "hi"}}),
        ]
        path.write_text("\n".join(lines) + "\n")
        archive = SessionArchive(path)
        assert len(archive.messages) == 2
        assert archive.messages[0].role == "user"

    def test_token_estimate(self):
        messages = [
            SessionMessage(type="human", role="user", content="x" * 400, turn_index=0),
        ]
        archive = SessionArchive(messages=messages)
        assert archive.token_estimate() == 100

    def test_to_jsonl_roundtrip(self, tmp_path):
        messages = [
            SessionMessage(type="human", role="user", content="hello", turn_index=0),
            SessionMessage(type="assistant", role="assistant", content="world", turn_index=1),
        ]
        archive = SessionArchive(messages=messages)
        path = tmp_path / "out.jsonl"
        archive.to_jsonl(path)
        archive2 = SessionArchive(path)
        assert len(archive2.messages) == 2


class TestSessionCompactor:
    def test_basic_compaction(self):
        messages = [
            SessionMessage(type="human", role="user", content="read file", turn_index=0),
            SessionMessage(type="tool_result", role="tool", content="x" * 200, turn_index=0),
            SessionMessage(type="human", role="user", content="read again", turn_index=1),
            SessionMessage(type="tool_result", role="tool", content="x" * 200, turn_index=1),
        ]
        archive = SessionArchive(messages=messages)
        compactor = SessionCompactor()
        compacted, result = compactor.compact(archive)
        assert result.dedup_hits == 1
        assert result.savings_pct > 0
        assert compacted.is_compacted

    def test_ansi_removal(self):
        messages = [
            SessionMessage(type="tool_result", role="tool",
                          content="\x1b[31merror\x1b[0m output here",
                          turn_index=0),
        ]
        archive = SessionArchive(messages=messages)
        compactor = SessionCompactor()
        compacted, result = compactor.compact(archive)
        assert result.ansi_stripped == 1
        assert "\x1b" not in compacted.messages[0].content

    def test_identical_turn_grouping(self):
        messages = [
            SessionMessage(type="human", role="user", content="do it", turn_index=0),
            SessionMessage(type="human", role="user", content="do it", turn_index=1),
            SessionMessage(type="human", role="user", content="do it", turn_index=2),
        ]
        archive = SessionArchive(messages=messages)
        compactor = SessionCompactor()
        compacted, _ = compactor.compact(archive)
        assert len(compacted.messages) == 1

    def test_config_disable_dedup(self):
        messages = [
            SessionMessage(type="tool_result", role="tool", content="x" * 200, turn_index=0),
            SessionMessage(type="tool_result", role="tool", content="x" * 200, turn_index=1),
        ]
        archive = SessionArchive(messages=messages)
        config = CompactConfig(deduplicate_tool_outputs=False)
        compactor = SessionCompactor(config)
        _, result = compactor.compact(archive)
        assert result.dedup_hits == 0


class TestSessionApplicator:
    def test_apply_anthropic_format(self):
        messages = [
            SessionMessage(type="human", role="user", content="hello", turn_index=0),
            SessionMessage(type="assistant", role="assistant", content="world", turn_index=1),
        ]
        archive = SessionArchive(messages=messages)
        applicator = SessionApplicator(format="anthropic")
        result = applicator.apply(archive, new_query="what next?")
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[2]["content"] == "what next?"

    def test_apply_openai_format(self):
        messages = [
            SessionMessage(type="human", role="user", content="hello", turn_index=0),
        ]
        archive = SessionArchive(messages=messages)
        applicator = SessionApplicator(format="openai")
        result = applicator.apply(archive)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_max_context_messages(self):
        messages = [
            SessionMessage(type="human", role="user", content=f"msg {i}", turn_index=i)
            for i in range(10)
        ]
        archive = SessionArchive(messages=messages)
        applicator = SessionApplicator(max_context_messages=3)
        result = applicator.apply(archive)
        assert len(result) == 3


class TestSessionExpander:
    def test_expand_not_compacted(self):
        messages = [
            SessionMessage(type="human", role="user", content="hello", turn_index=0),
        ]
        archive = SessionArchive(messages=messages)
        expander = SessionExpander()
        expanded = expander.expand(archive)
        assert expanded.messages == archive.messages
