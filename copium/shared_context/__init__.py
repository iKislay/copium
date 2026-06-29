"""Cross-Agent Context Sharing — persistent, searchable, provenance-tracked.

This package extends Copium's SharedContext with:
- SQLite-backed persistence (survives proxy restarts)
- Agent provenance tracking (who wrote what)
- Conflict resolution (configurable strategies)
- Vector search (semantic search over shared context)
- Audit logging (full operation trail)

Usage:

    from copium.shared_context import PersistentSharedContext

    ctx = PersistentSharedContext()

    # Agent A stores output (compressed + persisted)
    ctx.put("research", big_output, agent="researcher")

    # Agent B gets compressed version
    summary = ctx.get("research")

    # Semantic search across all shared context
    results = ctx.search("database migration findings", top_k=5)
"""

from copium.shared_context.audit_log import AuditAction, AuditLog, AuditRecord
from copium.shared_context.conflict_resolver import (
    ConflictResolver,
    ConflictResult,
    ConflictStrategy,
)
from copium.shared_context.eviction import EvictionConfig, EvictionManager, EvictionPolicy
from copium.shared_context.persistent_store import (
    PersistentContextEntry,
    PersistentStore,
    generate_entry_id,
)
from copium.shared_context.provenance import (
    AccessRecord,
    AgentIdentity,
    ContextProvenance,
)
from copium.shared_context.vector_index import VectorIndex, VectorSearchResult

__all__ = [
    "PersistentSharedContext",
    "PersistentStore",
    "PersistentContextEntry",
    "AgentIdentity",
    "ContextProvenance",
    "AccessRecord",
    "ConflictResolver",
    "ConflictResult",
    "ConflictStrategy",
    "VectorIndex",
    "VectorSearchResult",
    "EvictionConfig",
    "EvictionManager",
    "EvictionPolicy",
    "AuditLog",
    "AuditRecord",
    "AuditAction",
    "generate_entry_id",
]


import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PersistentSharedContext:
    """Persistent, searchable, provenance-tracked shared context for multi-agent workflows.

    Extends the in-memory SharedContext with:
    - SQLite-backed persistence
    - Agent provenance tracking
    - Configurable conflict resolution
    - Vector-based semantic search
    - Full audit trail

    Args:
        db_dir: Directory for database files. Defaults to ~/.copium/.
        model: Model name for compression pipeline.
        ttl: Default TTL in seconds (default: 3600 = 1 hour).
        max_entries: Maximum entries before eviction.
        conflict_strategy: How to resolve write conflicts.
        agent_priority: Agent priority order (for AGENT_PRIORITY strategy).
        audit: Whether to enable audit logging.
        project_id: Project scope for isolation.
    """

    def __init__(
        self,
        *,
        db_dir: str | Path | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        ttl: int = 3600,
        max_entries: int = 1000,
        conflict_strategy: ConflictStrategy = ConflictStrategy.LAST_WRITE_WINS,
        agent_priority: list[str] | None = None,
        audit: bool = True,
        project_id: str | None = None,
    ) -> None:
        self._model = model
        self._ttl = ttl
        self._project_id = project_id

        if db_dir is None:
            db_dir = Path.home() / ".copium"
        db_dir = Path(db_dir)
        db_dir.mkdir(parents=True, exist_ok=True)

        self._store = PersistentStore(
            db_path=db_dir / "shared_context.db",
            max_entries=max_entries,
        )
        self._vector_index = VectorIndex(
            db_path=db_dir / "shared_context_vectors.db",
        )
        self._conflict_resolver = ConflictResolver(
            strategy=conflict_strategy,
            agent_priority=agent_priority,
        )
        self._audit_log = AuditLog(
            db_path=db_dir / "shared_context_audit.db",
            enabled=audit,
        )
        self._eviction = EvictionManager(
            EvictionConfig(ttl_seconds=ttl, max_entries=max_entries)
        )

    def put(
        self,
        key: str,
        content: str,
        *,
        agent: str | None = None,
        provider: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        confidence: float = 0.9,
        tags: list[str] | None = None,
        ttl: int | None = None,
    ) -> PersistentContextEntry:
        """Store content under a key, compressing and persisting automatically.

        Args:
            key: Name for this context (e.g., "research_findings").
            content: The content to store and compress.
            agent: Agent name for provenance.
            provider: Provider name (anthropic, openai, etc.).
            session_id: Session ID for scoping.
            user_id: User ID for ownership.
            confidence: Confidence score (0.0-1.0).
            tags: User-defined tags for filtering.
            ttl: Custom TTL in seconds, or None for default.

        Returns:
            PersistentContextEntry with compression stats.
        """
        from copium.compress import compress

        # Compress via Copium pipeline
        messages = [{"role": "tool", "content": content}]
        result = compress(messages, model=self._model)

        compressed = result.messages[0].get("content", content)
        if not isinstance(compressed, str):
            import json
            compressed = json.dumps(compressed)

        # Check for conflict
        existing = self._store.get(key)
        entry_id = generate_entry_id()
        now = time.time()
        expires_at = self._eviction.compute_expiry(ttl)

        if existing and not existing.is_expired:
            # Resolve conflict
            existing_agent = AgentIdentity(agent_name=existing.agent or "unknown")
            new_agent = AgentIdentity(agent_name=agent or "unknown")
            resolution = self._conflict_resolver.resolve(
                existing_content=existing.content_compressed,
                existing_agent=existing_agent,
                existing_confidence=existing.confidence,
                existing_id=existing.id,
                new_content=compressed,
                new_agent=new_agent,
                new_confidence=confidence,
                new_id=entry_id,
            )
            # Log conflict
            self._audit_log.record(AuditRecord(
                action=AuditAction.CONFLICT,
                entry_key=key,
                entry_id=entry_id,
                agent_name=agent,
                session_id=session_id,
                user_id=user_id,
                details={
                    "strategy": resolution.strategy_used.value,
                    "winner": resolution.winner,
                    "merged": resolution.merged,
                },
            ))
            compressed = resolution.content

        entry = PersistentContextEntry(
            id=entry_id,
            key=key,
            content_original=content,
            content_compressed=compressed,
            agent=agent,
            provider=provider,
            session_id=session_id,
            user_id=user_id,
            project_id=self._project_id,
            original_tokens=result.tokens_before,
            compressed_tokens=result.tokens_after,
            transforms=result.transforms_applied,
            created_at=now,
            expires_at=expires_at,
            access_count=0,
            last_accessed=now,
            confidence=confidence,
            version=1 if not existing else existing.version + 1,
            tags=tags or [],
        )

        self._store.put(entry)

        # Audit
        self._audit_log.record(AuditRecord(
            action=AuditAction.PUT,
            entry_key=key,
            entry_id=entry_id,
            agent_name=agent,
            session_id=session_id,
            user_id=user_id,
            details={
                "original_tokens": result.tokens_before,
                "compressed_tokens": result.tokens_after,
                "savings_percent": entry.savings_percent,
                "transforms": result.transforms_applied,
            },
        ))

        logger.debug(
            "PersistentSharedContext.put(%s): %d → %d tokens (%.1f%% saved)",
            key, result.tokens_before, result.tokens_after, entry.savings_percent,
        )

        return entry

    def get(
        self,
        key: str,
        *,
        full: bool = False,
    ) -> str | None:
        """Get content by key.

        Args:
            key: The key to retrieve.
            full: If True, return original uncompressed content.

        Returns:
            Content string, or None if not found/expired.
        """
        entry = self._store.get(key)
        if entry is None:
            return None

        # Audit
        self._audit_log.record(AuditRecord(
            action=AuditAction.GET_FULL if full else AuditAction.GET,
            entry_key=key,
            entry_id=entry.id,
            agent_name=entry.agent,
        ))

        return entry.content_original if full else entry.content_compressed

    def get_entry(self, key: str) -> PersistentContextEntry | None:
        """Get the full entry with metadata."""
        return self._store.get(key)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_similarity: float = 0.3,
        agent_filter: str | None = None,
    ) -> list[VectorSearchResult]:
        """Semantic search over all shared context entries.

        Requires embeddings to have been generated for stored entries.
        Falls back to empty list if no vectors are indexed.

        Args:
            query: Natural language search query.
            top_k: Maximum results.
            min_similarity: Minimum cosine similarity.
            agent_filter: Filter results to specific agent.

        Returns:
            List of VectorSearchResult with similarity scores.
        """
        try:
            # Try to get embeddings from the memory system's embedder
            from copium.memory.factory import create_embedder
            embedder = create_embedder()
            query_vector = embedder.embed(query)
        except (ImportError, Exception) as e:
            logger.debug("Vector search unavailable: %s", e)
            return []

        results = self._vector_index.search(
            query_vector,
            top_k=top_k,
            min_similarity=min_similarity,
            agent_filter=agent_filter,
        )

        # Audit
        self._audit_log.record(AuditRecord(
            action=AuditAction.SEARCH,
            entry_key=query[:100],
            details={"top_k": top_k, "results_count": len(results)},
        ))

        return results

    def keys(self) -> list[str]:
        """List all non-expired keys."""
        return self._store.list_keys(project_id=self._project_id)

    def stats(self) -> dict[str, Any]:
        """Get aggregated statistics."""
        return self._store.stats(project_id=self._project_id)

    def delete(self, key: str) -> bool:
        """Delete all entries for a key."""
        success = self._store.delete(key)
        if success:
            self._audit_log.record(AuditRecord(
                action=AuditAction.DELETE,
                entry_key=key,
            ))
        return success

    def clear(self) -> int:
        """Remove all entries. Returns count removed."""
        count = self._store.clear()
        self._vector_index.clear()
        return count

    @property
    def audit_log(self) -> AuditLog:
        """Access the audit log for querying."""
        return self._audit_log
