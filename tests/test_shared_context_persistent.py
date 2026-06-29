"""Tests for the cross-agent shared context package."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from copium.shared_context import (
    AgentIdentity,
    AuditAction,
    AuditLog,
    ConflictResolver,
    ConflictStrategy,
    EvictionConfig,
    EvictionManager,
    PersistentContextEntry,
    PersistentStore,
    VectorIndex,
    generate_entry_id,
)
from copium.shared_context.provenance import AccessRecord, ContextProvenance


class TestPersistentStore:
    """Tests for SQLite-backed persistent store."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self.store = PersistentStore(
            db_path=Path(self._tmpdir) / "test.db",
            max_entries=10,
        )

    def _make_entry(self, key: str = "test", **kwargs) -> PersistentContextEntry:
        defaults = {
            "id": generate_entry_id(),
            "key": key,
            "content_original": "original content here",
            "content_compressed": "compressed",
            "agent": "test_agent",
            "provider": "openai",
            "session_id": "sess-1",
            "user_id": "user-1",
            "project_id": "proj-1",
            "original_tokens": 1000,
            "compressed_tokens": 200,
            "transforms": ["router:json:0.20"],
            "created_at": time.time(),
            "expires_at": time.time() + 3600,
            "access_count": 0,
            "last_accessed": time.time(),
            "confidence": 0.9,
            "version": 1,
            "tags": ["research"],
        }
        defaults.update(kwargs)
        return PersistentContextEntry(**defaults)

    def test_put_and_get(self):
        entry = self._make_entry("findings")
        self.store.put(entry)
        retrieved = self.store.get("findings")
        assert retrieved is not None
        assert retrieved.key == "findings"
        assert retrieved.content_original == "original content here"
        assert retrieved.agent == "test_agent"

    def test_get_nonexistent(self):
        assert self.store.get("nonexistent") is None

    def test_get_expired(self):
        entry = self._make_entry("expired", expires_at=time.time() - 1)
        self.store.put(entry)
        assert self.store.get("expired") is None

    def test_list_keys(self):
        self.store.put(self._make_entry("key1"))
        self.store.put(self._make_entry("key2"))
        keys = self.store.list_keys()
        assert "key1" in keys
        assert "key2" in keys

    def test_delete(self):
        self.store.put(self._make_entry("to_delete"))
        assert self.store.delete("to_delete") is True
        assert self.store.get("to_delete") is None

    def test_stats(self):
        self.store.put(self._make_entry("s1", original_tokens=500, compressed_tokens=100))
        self.store.put(self._make_entry("s2", original_tokens=500, compressed_tokens=100))
        stats = self.store.stats()
        assert stats["entries"] == 2
        assert stats["total_original_tokens"] == 1000
        assert stats["total_compressed_tokens"] == 200

    def test_eviction_on_capacity(self):
        # Fill to capacity (max_entries=10)
        for i in range(12):
            self.store.put(self._make_entry(f"key_{i}"))
        keys = self.store.list_keys()
        assert len(keys) <= 10


class TestConflictResolver:
    """Tests for conflict resolution strategies."""

    def test_last_write_wins(self):
        resolver = ConflictResolver(strategy=ConflictStrategy.LAST_WRITE_WINS)
        result = resolver.resolve(
            existing_content="old", existing_agent=None,
            existing_confidence=0.9, existing_id="id1",
            new_content="new", new_agent=None,
            new_confidence=0.5, new_id="id2",
        )
        assert result.content == "new"
        assert result.winner == "id2"

    def test_highest_confidence_wins(self):
        resolver = ConflictResolver(strategy=ConflictStrategy.HIGHEST_CONFIDENCE)
        result = resolver.resolve(
            existing_content="high_conf",
            existing_agent=AgentIdentity(agent_name="a"),
            existing_confidence=0.95, existing_id="id1",
            new_content="low_conf",
            new_agent=AgentIdentity(agent_name="b"),
            new_confidence=0.5, new_id="id2",
        )
        assert result.content == "high_conf"
        assert result.winner == "id1"

    def test_agent_priority(self):
        resolver = ConflictResolver(
            strategy=ConflictStrategy.AGENT_PRIORITY,
            agent_priority=["senior", "junior"],
        )
        result = resolver.resolve(
            existing_content="junior_output",
            existing_agent=AgentIdentity(agent_name="junior"),
            existing_confidence=0.9, existing_id="id1",
            new_content="senior_output",
            new_agent=AgentIdentity(agent_name="senior"),
            new_confidence=0.9, new_id="id2",
        )
        assert result.content == "senior_output"

    def test_merge(self):
        resolver = ConflictResolver(strategy=ConflictStrategy.MERGE)
        result = resolver.resolve(
            existing_content="part A",
            existing_agent=None,
            existing_confidence=0.9, existing_id="id1",
            new_content="part B",
            new_agent=None,
            new_confidence=0.9, new_id="id2",
        )
        assert "part A" in result.content
        assert "part B" in result.content
        assert result.merged is True


class TestVectorIndex:
    """Tests for vector search."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self.index = VectorIndex(
            db_path=Path(self._tmpdir) / "vectors.db",
            dimension=4,  # Small dimension for testing
        )

    def test_add_and_search(self):
        self.index.add("entry1", "research", [1.0, 0.0, 0.0, 0.0], agent="researcher")
        self.index.add("entry2", "code", [0.0, 1.0, 0.0, 0.0], agent="coder")

        results = self.index.search([1.0, 0.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0].entry_id == "entry1"
        assert results[0].similarity > 0.99

    def test_filter_by_agent(self):
        self.index.add("e1", "k1", [1.0, 0.0, 0.0, 0.0], agent="a")
        self.index.add("e2", "k2", [0.9, 0.1, 0.0, 0.0], agent="b")

        results = self.index.search(
            [1.0, 0.0, 0.0, 0.0], agent_filter="a"
        )
        assert all(r.agent == "a" for r in results)

    def test_min_similarity(self):
        self.index.add("e1", "k1", [1.0, 0.0, 0.0, 0.0])
        self.index.add("e2", "k2", [0.0, 0.0, 0.0, 1.0])

        results = self.index.search(
            [1.0, 0.0, 0.0, 0.0], min_similarity=0.5
        )
        assert len(results) == 1


class TestAuditLog:
    """Tests for audit logging."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self.audit = AuditLog(
            db_path=Path(self._tmpdir) / "audit.db",
            enabled=True,
        )

    def test_record_and_query(self):
        from copium.shared_context.audit_log import AuditRecord

        self.audit.record(AuditRecord(
            action=AuditAction.PUT,
            entry_key="test_key",
            agent_name="researcher",
        ))
        records = self.audit.query(agent_name="researcher")
        assert len(records) == 1
        assert records[0].action == AuditAction.PUT

    def test_count(self):
        from copium.shared_context.audit_log import AuditRecord

        for i in range(5):
            self.audit.record(AuditRecord(
                action=AuditAction.GET,
                entry_key=f"key_{i}",
            ))
        assert self.audit.count() == 5


class TestProvenance:
    """Tests for agent provenance tracking."""

    def test_agent_identity_from_headers(self):
        headers = {
            "x-copium-agent": "researcher",
            "x-copium-agent-provider": "anthropic",
            "x-copium-agent-model": "claude-sonnet-4-5-20250929",
            "x-copium-session-id": "sess-123",
        }
        identity = AgentIdentity.from_headers(headers)
        assert identity.agent_name == "researcher"
        assert identity.provider == "anthropic"
        assert identity.model == "claude-sonnet-4-5-20250929"

    def test_provenance_versioning(self):
        agent = AgentIdentity(agent_name="test")
        prov = ContextProvenance.create("entry-1", agent)
        assert prov.version == 1

        prov.record_modification(AgentIdentity(agent_name="updater"))
        assert prov.version == 2
        assert prov.last_modified_by.agent_name == "updater"


class TestEviction:
    """Tests for eviction manager."""

    def test_compute_expiry(self):
        mgr = EvictionManager(EvictionConfig(ttl_seconds=60))
        expiry = mgr.compute_expiry()
        assert expiry > time.time()
        assert expiry <= time.time() + 61

    def test_should_evict(self):
        mgr = EvictionManager(EvictionConfig(max_entries=100))
        assert mgr.should_evict(99) is False
        assert mgr.should_evict(100) is True

    def test_custom_ttl_override(self):
        mgr = EvictionManager(EvictionConfig(ttl_seconds=3600))
        expiry = mgr.compute_expiry(ttl_override=60)
        assert expiry < time.time() + 61
