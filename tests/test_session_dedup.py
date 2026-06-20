"""Tests for SessionDedup transform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from copium.config import SessionDedupConfig
from copium.transforms.session_dedup import (
    SessionDedup,
    _content_hash,
    _jaccard_similarity,
    _make_retrieval_marker,
    _minhash_signature,
)


@pytest.fixture
def tokenizer():
    """Mock tokenizer that counts words as tokens."""
    tok = MagicMock()
    tok.count_messages.return_value = 100
    tok.count_text.return_value = 50
    return tok


@pytest.fixture
def dedup():
    """SessionDedup with default config."""
    return SessionDedup(SessionDedupConfig())


@pytest.fixture
def dedup_strict():
    """SessionDedup with strict config (low threshold)."""
    return SessionDedup(
        SessionDedupConfig(minhash_threshold=0.5, min_content_length=10)
    )


class TestContentHash:
    def test_exact_match(self):
        text = "Hello world, this is a test output."
        h1 = _content_hash(text)
        h2 = _content_hash(text)
        assert h1 == h2

    def test_different_content(self):
        h1 = _content_hash("Content A")
        h2 = _content_hash("Content B")
        assert h1 != h2

    def test_ansi_stripped(self):
        text_clean = "Error: something failed"
        text_ansi = "\x1b[31mError:\x1b[0m something failed"
        assert _content_hash(text_clean) == _content_hash(text_ansi)

    def test_whitespace_normalized(self):
        assert _content_hash("  hello  ") == _content_hash("hello")


class TestMinHash:
    def test_identical_content(self):
        sig1 = _minhash_signature("This is identical content for testing purposes.")
        sig2 = _minhash_signature("This is identical content for testing purposes.")
        assert _jaccard_similarity(sig1, sig2) == 1.0

    def test_similar_content(self):
        text_a = "npm install completed in 4.5 seconds. 234 packages installed."
        text_b = "npm install completed in 4.7 seconds. 234 packages installed."
        sig_a = _minhash_signature(text_a)
        sig_b = _minhash_signature(text_b)
        sim = _jaccard_similarity(sig_a, sig_b)
        assert sim > 0.7  # Should be quite similar

    def test_different_content(self):
        sig_a = _minhash_signature("Python code execution output with stack trace.")
        sig_b = _minhash_signature("Docker build failed with network timeout error.")
        sim = _jaccard_similarity(sig_a, sig_b)
        assert sim < 0.5

    def test_empty_content(self):
        sig = _minhash_signature("")
        assert len(sig) == 128  # Default num_perm


class TestRetrievalMarker:
    def test_basic_marker(self):
        marker = _make_retrieval_marker(first_seen_turn=3, content_len=500)
        assert "turn 3" in marker
        assert "500 chars" in marker
        assert "[Session dedup:" in marker

    def test_marker_with_tool_name(self):
        marker = _make_retrieval_marker(
            first_seen_turn=1, content_len=1024, tool_name="Read"
        )
        assert "Read output" in marker
        assert "turn 1" in marker


class TestSessionDedup:
    def test_no_dedup_on_system_messages(self, dedup, tokenizer):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = dedup.apply(messages, tokenizer)
        assert result.transforms_applied == []
        assert result.messages == messages

    def test_no_dedup_short_content(self, dedup, tokenizer):
        messages = [
            {"role": "tool", "content": "short"},
            {"role": "tool", "content": "short"},
        ]
        result = dedup.apply(messages, tokenizer)
        # Both are too short (default min_content_length=200)
        assert result.transforms_applied == []

    def test_exact_dedup(self, dedup_strict, tokenizer):
        long_content = "x" * 300  # Above min_content_length=10
        messages = [
            {"role": "tool", "content": long_content, "name": "Bash"},
            {"role": "assistant", "content": "Done"},
            {"role": "tool", "content": long_content, "name": "Bash"},
        ]
        result = dedup_strict.apply(messages, tokenizer)
        # First occurrence kept, second deduplicated
        assert len([t for t in result.transforms_applied if "session_dedup" in t]) == 1
        # Second message should have marker
        assert "Session dedup" in result.messages[2]["content"]

    def test_no_dedup_different_content(self, dedup_strict, tokenizer):
        messages = [
            {"role": "tool", "content": "A" * 300, "name": "Bash"},
            {"role": "tool", "content": "B" * 300, "name": "Bash"},
        ]
        result = dedup_strict.apply(messages, tokenizer)
        assert result.transforms_applied == []

    def test_disabled_config(self, tokenizer):
        dedup = SessionDedup(SessionDedupConfig(enabled=False))
        messages = [
            {"role": "tool", "content": "x" * 300},
            {"role": "tool", "content": "x" * 300},
        ]
        result = dedup.apply(messages, tokenizer)
        assert result.transforms_applied == []
        assert result.tokens_before == result.tokens_after

    def test_preserves_user_messages(self, dedup_strict, tokenizer):
        messages = [
            {"role": "user", "content": "Please read file.py"},
            {"role": "tool", "content": "file content " * 30},
            {"role": "user", "content": "Please read file.py again"},
            {"role": "tool", "content": "file content " * 30},
        ]
        result = dedup_strict.apply(messages, tokenizer)
        # User messages should never be deduplicated
        assert result.messages[0]["role"] == "user"
        assert result.messages[2]["role"] == "user"
        # Tool output should be deduplicated
        assert "Session dedup" in result.messages[3]["content"]

    def test_eviction(self, tokenizer):
        dedup = SessionDedup(
            SessionDedupConfig(max_session_hashes=5, min_content_length=10)
        )
        messages = []
        for i in range(10):
            messages.append({"role": "tool", "content": f"content_{i} " * 20})
        result = dedup.apply(messages, tokenizer)
        # Should have processed all messages without error
        assert len(result.messages) == 10

    def test_marker_in_result(self, dedup_strict, tokenizer):
        content = "test content " * 30
        messages = [
            {"role": "tool", "content": content, "name": "Read"},
            {"role": "tool", "content": content, "name": "Read"},
        ]
        result = dedup_strict.apply(messages, tokenizer)
        assert "Session dedup" in result.messages[1]["content"]
        assert "_copium_session_dedup" in result.messages[1]

    def test_file_tool_eligibility(self, tokenizer):
        dedup = SessionDedup(
            SessionDedupConfig(eligible_content="file", min_content_length=10)
        )
        content = "file content " * 20
        messages = [
            {"role": "tool", "content": content, "name": "Read"},
            {"role": "tool", "content": content, "name": "Bash"},
        ]
        result = dedup.apply(messages, tokenizer)
        # Only Read should be eligible, Bash should not
        # Both are different tools so no dedup anyway
        assert result.transforms_applied == []


class TestSessionDedupConfig:
    def test_defaults(self):
        config = SessionDedupConfig()
        assert config.enabled is True
        assert config.exact_hash is True
        assert config.minhash_enabled is True
        assert config.minhash_threshold == 0.85
        assert config.max_session_hashes == 10_000

    def test_custom_config(self):
        config = SessionDedupConfig(
            enabled=False,
            minhash_threshold=0.7,
            max_session_hashes=1000,
        )
        assert config.enabled is False
        assert config.minhash_threshold == 0.7
        assert config.max_session_hashes == 1000
