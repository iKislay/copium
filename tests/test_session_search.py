"""Tests for session search (FTS5 index)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from copium.session.search import SearchConfig, SessionSearch
from copium.session.archive import SessionMessage


class TestSessionSearch:
    """Tests for the FTS5 session search."""

    @pytest.fixture
    def searcher(self, tmp_path):
        config = SearchConfig(index_path=tmp_path / "test_index.db")
        s = SessionSearch(config)
        yield s
        s.close()

    @pytest.fixture
    def sample_messages(self):
        return [
            SessionMessage(type="human", role="user", content="Fix the authentication bug in src/auth.ts", turn_index=0),
            SessionMessage(type="assistant", role="assistant", content="I will fix the auth middleware.", turn_index=1),
            SessionMessage(type="tool_result", role="tool", content="export function authenticate(req) { ... }", turn_index=1),
        ]

    def test_index_and_search(self, searcher, sample_messages, tmp_path):
        # Create a fake session file
        session_path = tmp_path / "session.jsonl"
        session_path.write_text("
".join([
            json.dumps({"type": m.type, "message": {"role": m.role, "content": m.content}})
            for m in sample_messages
        ]))

        # Index it
        count = searcher.index_session(session_path, agent="claude_code", messages=sample_messages)
        assert count == 3

        # Search
        results = searcher.search("authentication")
        assert len(results) > 0
        assert "auth" in results[0].content_snippet.lower()

    def test_search_by_agent(self, searcher, sample_messages, tmp_path):
        session_path = tmp_path / "session.jsonl"
        session_path.touch()

        searcher.index_session(session_path, agent="claude_code", messages=sample_messages)

        # Search with agent filter
        results = searcher.search("auth", agent="claude_code")
        assert len(results) > 0

        # Search with wrong agent
        results = searcher.search("auth", agent="cursor")
        assert len(results) == 0

    def test_search_by_role(self, searcher, sample_messages, tmp_path):
        session_path = tmp_path / "session.jsonl"
        session_path.touch()

        searcher.index_session(session_path, agent="test", messages=sample_messages)

        # Search only user messages
        results = searcher.search("authentication", role="user")
        assert len(results) > 0
        assert all(r.role == "user" for r in results)

    def test_search_file_reference(self, searcher, sample_messages, tmp_path):
        session_path = tmp_path / "session.jsonl"
        session_path.touch()

        searcher.index_session(session_path, agent="test", messages=sample_messages)

        results = searcher.search_file("src/auth.ts")
        assert len(results) > 0

    def test_stats(self, searcher, sample_messages, tmp_path):
        session_path = tmp_path / "session.jsonl"
        session_path.touch()

        searcher.index_session(session_path, agent="claude_code", messages=sample_messages)

        stats = searcher.stats()
        assert stats["sessions"] == 1
        assert stats["messages"] == 3
        assert "claude_code" in stats["agents"]

    def test_no_results(self, searcher):
        results = searcher.search("nonexistent_xyz_query")
        assert results == []

    def test_skip_reindex_unchanged(self, searcher, sample_messages, tmp_path):
        session_path = tmp_path / "session.jsonl"
        session_path.write_text("test")

        count1 = searcher.index_session(session_path, agent="test", messages=sample_messages)
        assert count1 == 3

        # Second index should skip (file unchanged)
        count2 = searcher.index_session(session_path, agent="test", messages=sample_messages)
        assert count2 == 0
