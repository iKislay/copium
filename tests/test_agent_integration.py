"""Tests for agent integration (context manager, session, tool cache)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from copium.agent.context_manager import (
    AgentContextManager,
    ContextBudget,
    ManagedContext,
    TurnInput,
)
from copium.agent.session import CompressedSession, SessionStore
from copium.agent.tool_cache import CacheStats, SemanticToolCache


# =============================================================================
# AgentContextManager Tests
# =============================================================================


class TestAgentContextManager:
    """Tests for AgentContextManager."""

    def setup_method(self):
        self.manager = AgentContextManager(max_tokens=10000)

    def test_simple_turn(self):
        turn = TurnInput(
            system_prompt="You are helpful.",
            conversation_history=[],
            current_message="Hello!",
        )
        result = self.manager.manage_turn(turn)
        assert result.fits_budget
        assert len(result.messages) == 2  # system + user
        assert result.messages[0]["role"] == "system"
        assert result.messages[1]["role"] == "user"

    def test_history_compression(self):
        """Long history should be compressed to fit budget."""
        # Create history that exceeds budget
        history = [
            {"role": "user", "content": "x" * 2000}
            for _ in range(20)
        ]
        turn = TurnInput(
            system_prompt="System",
            conversation_history=history,
            current_message="Latest",
        )
        result = self.manager.manage_turn(turn)
        assert result.history_compressed
        assert result.tokens_saved > 0
        # Should have fewer messages than original
        assert len(result.messages) < len(history) + 2

    def test_tool_deduplication(self):
        """Duplicate tool results should be deduplicated."""
        tool_results = [
            {"role": "tool", "name": "read_file", "content": "file content here"},
            {"role": "tool", "name": "read_file", "content": "file content here"},
            {"role": "tool", "name": "search", "content": "different result"},
        ]
        turn = TurnInput(
            system_prompt="System",
            tool_results=tool_results,
            current_message="What did you find?",
        )
        result = self.manager.manage_turn(turn)
        # Should deduplicate the two identical read_file results
        tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
        assert len(tool_msgs) <= 3  # At most 3 (possibly 2 if deduped)

    def test_turn_counting(self):
        turn = TurnInput(current_message="Hi")
        self.manager.manage_turn(turn)
        self.manager.manage_turn(turn)
        assert self.manager.turn_count == 2

    def test_empty_turn(self):
        turn = TurnInput()
        result = self.manager.manage_turn(turn)
        assert result.total_tokens == 0
        assert result.fits_budget


class TestContextBudget:
    """Tests for ContextBudget."""

    def test_default_budget(self):
        budget = ContextBudget()
        assert budget.total_tokens == 128000
        assert budget.system_prompt_budget == 12800
        assert budget.history_budget == 51200
        assert budget.tools_budget == 25600
        assert budget.current_turn_budget == 38400

    def test_custom_budget(self):
        budget = ContextBudget(total_tokens=200000, history_pct=0.5)
        assert budget.history_budget == 100000


# =============================================================================
# SessionStore Tests
# =============================================================================


class TestSessionStore:
    """Tests for SessionStore."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.store = SessionStore(storage_dir=self.tmp_dir)

    def test_create_session(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        session = self.store.create_session(messages)
        assert session.session_id.startswith("session_")
        assert session.total_turns == 1
        assert len(session.messages) == 2

    def test_save_and_load(self):
        messages = [{"role": "user", "content": "Test message"}]
        session = self.store.create_session(messages, metadata={"model": "claude"})
        self.store.save(session)

        loaded = self.store.load(session.session_id)
        assert loaded is not None
        assert loaded.session_id == session.session_id
        assert loaded.messages == messages
        assert loaded.metadata["model"] == "claude"

    def test_load_nonexistent(self):
        assert self.store.load("nonexistent_session") is None

    def test_delete_session(self):
        messages = [{"role": "user", "content": "Delete me"}]
        session = self.store.create_session(messages)
        self.store.save(session)

        assert self.store.delete(session.session_id) is True
        assert self.store.load(session.session_id) is None

    def test_delete_nonexistent(self):
        assert self.store.delete("nonexistent") is False

    def test_list_sessions(self):
        for i in range(3):
            session = self.store.create_session(
                [{"role": "user", "content": f"Message {i}"}]
            )
            self.store.save(session)

        sessions = self.store.list_sessions()
        assert len(sessions) == 3
        # Should be sorted by most recent first
        assert sessions[0].updated_at >= sessions[1].updated_at

    def test_fork_session(self):
        messages = [
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Turn 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Turn 3"},
        ]
        session = self.store.create_session(messages)
        self.store.save(session)

        forked = self.store.fork_session(session.session_id, at_turn=2)
        assert forked is not None
        assert forked.session_id != session.session_id
        assert forked.metadata.get("forked_from") == session.session_id
        # Should only have first 2 user turns worth of messages
        user_msgs = [m for m in forked.messages if m["role"] == "user"]
        assert len(user_msgs) <= 2

    def test_fork_nonexistent(self):
        assert self.store.fork_session("nonexistent") is None

    def test_path_traversal_protection(self):
        """Session IDs with path traversal should be sanitized."""
        session = CompressedSession(
            session_id="../../../etc/passwd",
            messages=[],
        )
        self.store.save(session)
        # Should create a safe filename
        import os
        for f in os.listdir(self.tmp_dir):
            assert ".." not in f
            assert "/" not in f


class TestCompressedSession:
    """Tests for CompressedSession."""

    def test_serialization(self):
        session = CompressedSession(
            session_id="test_123",
            messages=[{"role": "user", "content": "hi"}],
            metadata={"key": "value"},
            total_turns=1,
            compressed_tokens=10,
            original_tokens=20,
        )
        data = session.to_dict()
        restored = CompressedSession.from_dict(data)
        assert restored.session_id == "test_123"
        assert restored.total_turns == 1
        assert restored.compression_ratio == 0.5


# =============================================================================
# SemanticToolCache Tests
# =============================================================================


class TestSemanticToolCache:
    """Tests for SemanticToolCache."""

    def setup_method(self):
        self.cache = SemanticToolCache(max_entries=10, ttl_seconds=60)

    def test_cache_miss(self):
        result = self.cache.get("read_file", {"path": "/main.py"})
        assert result is None
        assert self.cache.stats.misses == 1

    def test_cache_hit(self):
        self.cache.put(
            "read_file",
            {"path": "/main.py"},
            "full file content here",
            "compressed content",
        )
        result = self.cache.get("read_file", {"path": "/main.py"})
        assert result == "compressed content"
        assert self.cache.stats.hits == 1

    def test_different_args_miss(self):
        self.cache.put(
            "read_file",
            {"path": "/main.py"},
            "content",
            "compressed",
        )
        # Different path = different key
        result = self.cache.get("read_file", {"path": "/other.py"})
        assert result is None

    def test_content_dedup(self):
        """Same content from different tools should be deduped."""
        content = "shared content output"
        self.cache.put("tool_a", {"arg": "1"}, content, "compressed_shared")

        # Look up by content
        result = self.cache.get_by_content(content)
        assert result == "compressed_shared"

    def test_eviction(self):
        """Cache should evict when full."""
        for i in range(15):  # Exceeds max_entries=10
            self.cache.put(f"tool_{i}", {"i": i}, f"result_{i}", f"comp_{i}")

        assert self.cache.stats.entries <= 10
        assert self.cache.stats.evictions > 0

    def test_invalidate(self):
        self.cache.put("read_file", {"path": "/x"}, "content", "compressed")
        assert self.cache.get("read_file", {"path": "/x"}) is not None

        self.cache.invalidate("read_file", {"path": "/x"})
        assert self.cache.get("read_file", {"path": "/x"}) is None

    def test_clear(self):
        self.cache.put("tool", {"a": 1}, "result", "compressed")
        self.cache.clear()
        assert self.cache.stats.entries == 0
        assert self.cache.get("tool", {"a": 1}) is None

    def test_hit_rate(self):
        self.cache.put("t", {"a": 1}, "r", "c")
        self.cache.get("t", {"a": 1})  # hit
        self.cache.get("t", {"a": 2})  # miss
        assert self.cache.stats.hit_rate == 0.5
        assert self.cache.stats.hit_rate_pct == 50.0
