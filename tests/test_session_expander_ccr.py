"""Tests for session expander with CCR store bridge."""

from __future__ import annotations

import pytest

from copium.session.archive import SessionArchive, SessionMessage
from copium.session.expander import SessionExpander


class InMemoryCCRStore:
    """Test double for CCR store."""

    def __init__(self, data: dict[str, str] | None = None):
        self._data = data or {}

    def get(self, hash_key: str) -> str | None:
        return self._data.get(hash_key)

    def has(self, hash_key: str) -> bool:
        return hash_key in self._data


class TestSessionExpanderCCR:
    """Tests for CCR store bridge in SessionExpander."""

    def test_expand_from_ccr_store(self):
        """CCR store provides original content for deduped messages."""
        store = InMemoryCCRStore({
            "abc123def456": "original file content that was deduplicated",
        })

        messages = [
            SessionMessage(
                type="human", role="user", content="Read the file",
                turn_index=0,
            ),
            SessionMessage(
                type="tool_result", role="tool",
                content="[Session dedup: Content identical to turn 0 (100 chars)]",
                metadata={"_ccr_hash": "abc123def456", "_dedup_ref": 0},
                turn_index=1,
            ),
        ]

        archive = SessionArchive(messages=messages)
        archive._metadata = {"_copium_compacted": True}

        expander = SessionExpander(ccr_store=store)
        expanded = expander.expand(archive)

        assert expanded.messages[1].content == "original file content that was deduplicated"

    def test_expand_ccr_miss_falls_through(self):
        """When CCR miss, keeps the dedup marker in place."""
        store = InMemoryCCRStore({})  # Empty store

        messages = [
            SessionMessage(
                type="tool_result", role="tool",
                content="[Session dedup: Content identical to turn 0 (100 chars)]",
                metadata={"_ccr_hash": "nonexistent_hash", "_dedup_ref": 0},
                turn_index=1,
            ),
        ]

        archive = SessionArchive(messages=messages)
        archive._metadata = {"_copium_compacted": True}

        expander = SessionExpander(ccr_store=store)
        expanded = expander.expand(archive)

        # Marker remains since no recovery source available
        assert "Session dedup" in expanded.messages[0].content

    def test_expand_ccr_with_content_hash(self):
        """CCR store retrieval via _content_hash metadata."""
        store = InMemoryCCRStore({
            "fedcba987654": "recovered via content hash",
        })

        messages = [
            SessionMessage(
                type="tool_result", role="tool",
                content="[Session dedup: Content near-identical to turn 2]",
                metadata={"_content_hash": "fedcba987654"},
                turn_index=3,
            ),
        ]

        archive = SessionArchive(messages=messages)
        archive._metadata = {"_copium_compacted": True}

        expander = SessionExpander(ccr_store=store)
        expanded = expander.expand(archive)

        assert expanded.messages[0].content == "recovered via content hash"

    def test_expand_non_compacted_returns_asis(self):
        """Non-compacted archives are returned unchanged."""
        store = InMemoryCCRStore({"hash": "content"})

        messages = [
            SessionMessage(
                type="human", role="user", content="hello",
                turn_index=0,
            ),
        ]

        archive = SessionArchive(messages=messages)
        # No _copium_compacted metadata

        expander = SessionExpander(ccr_store=store)
        result = expander.expand(archive)

        assert result.messages[0].content == "hello"

    def test_expand_mixed_ccr_and_original(self, tmp_path):
        """Uses CCR for some messages, original archive for others."""
        store = InMemoryCCRStore({
            "hash_turn_1": "content from CCR store",
        })

        # Original archive
        original_messages = [
            SessionMessage(type="human", role="user", content="q1", turn_index=0),
            SessionMessage(type="tool_result", role="tool", content="content from CCR store", turn_index=1),
            SessionMessage(type="tool_result", role="tool", content="content from original", turn_index=2),
        ]
        original_path = tmp_path / "original.jsonl"
        original_archive = SessionArchive(messages=original_messages)
        original_archive.to_jsonl(original_path)

        # Compacted archive
        compacted_messages = [
            SessionMessage(type="human", role="user", content="q1", turn_index=0),
            SessionMessage(
                type="tool_result", role="tool",
                content="[Session dedup: Content identical to turn 1]",
                metadata={"_ccr_hash": "hash_turn_1", "_dedup_ref": 1},
                turn_index=1,
            ),
            SessionMessage(
                type="tool_result", role="tool",
                content="[Session dedup: Content identical to turn 2]",
                metadata={"_dedup_ref": 2},
                turn_index=2,
            ),
        ]
        compacted = SessionArchive(messages=compacted_messages)
        compacted._metadata = {"_copium_compacted": True}

        expander = SessionExpander(ccr_store=store, original_path=original_path)
        expanded = expander.expand(compacted)

        # Turn 1 recovered from CCR
        assert expanded.messages[1].content == "content from CCR store"

    def test_expand_strips_internal_metadata(self):
        """Internal metadata (_ccr_hash, _dedup_ref) is stripped after expansion."""
        store = InMemoryCCRStore({
            "test_hash": "expanded content",
        })

        messages = [
            SessionMessage(
                type="tool_result", role="tool",
                content="[dedup marker]",
                metadata={"_ccr_hash": "test_hash", "_dedup_ref": 0, "tool_name": "read_file"},
                turn_index=1,
            ),
        ]

        archive = SessionArchive(messages=messages)
        archive._metadata = {"_copium_compacted": True}

        expander = SessionExpander(ccr_store=store)
        expanded = expander.expand(archive)

        # Internal metadata removed, user metadata preserved
        assert "_ccr_hash" not in expanded.messages[0].metadata
        assert "_dedup_ref" not in expanded.messages[0].metadata
