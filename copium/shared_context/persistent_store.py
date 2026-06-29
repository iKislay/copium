"""Persistent SQLite-backed storage for SharedContext entries.

Provides durable cross-agent context sharing that survives proxy restarts.
Uses SQLite for storage with TTL-based expiration and LRU eviction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default database path under .copium/
_DEFAULT_DB_DIR = Path.home() / ".copium"
_DEFAULT_DB_NAME = "shared_context.db"


@dataclass
class PersistentContextEntry:
    """A stored context entry with full metadata for persistent storage."""

    id: str
    key: str
    content_original: str
    content_compressed: str
    agent: str | None
    provider: str | None
    session_id: str | None
    user_id: str | None
    project_id: str | None
    original_tokens: int
    compressed_tokens: int
    transforms: list[str] = field(default_factory=list)
    created_at: float = 0.0
    expires_at: float = 0.0
    access_count: int = 0
    last_accessed: float = 0.0
    confidence: float = 0.9
    version: int = 1
    tags: list[str] = field(default_factory=list)

    @property
    def savings_percent(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return round((1 - self.compressed_tokens / self.original_tokens) * 100, 1)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class PersistentStore:
    """SQLite-backed persistent store for shared context entries.

    Thread-safe, supports TTL-based expiration and LRU eviction.

    Args:
        db_path: Path to SQLite database file. Defaults to ~/.copium/shared_context.db.
        max_entries: Maximum entries to store before eviction.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        max_entries: int = 1000,
    ) -> None:
        if db_path is None:
            _DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
            db_path = _DEFAULT_DB_DIR / _DEFAULT_DB_NAME
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indices if they don't exist."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS shared_context_entries (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    content_original TEXT,
                    content_compressed TEXT,
                    agent TEXT,
                    provider TEXT,
                    session_id TEXT,
                    user_id TEXT,
                    project_id TEXT,
                    original_tokens INTEGER NOT NULL,
                    compressed_tokens INTEGER NOT NULL,
                    transforms TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed REAL NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.9,
                    version INTEGER NOT NULL DEFAULT 1,
                    tags TEXT NOT NULL DEFAULT '[]'
                );

                CREATE INDEX IF NOT EXISTS idx_sc_key
                    ON shared_context_entries(key);
                CREATE INDEX IF NOT EXISTS idx_sc_agent
                    ON shared_context_entries(agent);
                CREATE INDEX IF NOT EXISTS idx_sc_session
                    ON shared_context_entries(session_id);
                CREATE INDEX IF NOT EXISTS idx_sc_project
                    ON shared_context_entries(project_id);
                CREATE INDEX IF NOT EXISTS idx_sc_expires
                    ON shared_context_entries(expires_at);
                CREATE INDEX IF NOT EXISTS idx_sc_last_accessed
                    ON shared_context_entries(last_accessed);
            """)

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection with WAL mode for concurrent reads."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def put(self, entry: PersistentContextEntry) -> PersistentContextEntry:
        """Store or update an entry.

        If an entry with the same key exists, it is replaced (last-write-wins).
        """
        with self._lock:
            with self._connect() as conn:
                # Evict expired entries first
                self._evict_expired(conn)

                # Check capacity
                count = conn.execute(
                    "SELECT COUNT(*) FROM shared_context_entries"
                ).fetchone()[0]
                if count >= self._max_entries:
                    self._evict_lru(conn, count - self._max_entries + 1)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO shared_context_entries
                    (id, key, content_original, content_compressed, agent, provider,
                     session_id, user_id, project_id, original_tokens, compressed_tokens,
                     transforms, created_at, expires_at, access_count, last_accessed,
                     confidence, version, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.key,
                        entry.content_original,
                        entry.content_compressed,
                        entry.agent,
                        entry.provider,
                        entry.session_id,
                        entry.user_id,
                        entry.project_id,
                        entry.original_tokens,
                        entry.compressed_tokens,
                        json.dumps(entry.transforms),
                        entry.created_at,
                        entry.expires_at,
                        entry.access_count,
                        entry.last_accessed,
                        entry.confidence,
                        entry.version,
                        json.dumps(entry.tags),
                    ),
                )
        logger.debug("PersistentStore.put(%s): stored entry %s", entry.key, entry.id)
        return entry

    def get(self, key: str) -> PersistentContextEntry | None:
        """Retrieve an entry by key. Returns None if not found or expired."""
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM shared_context_entries
                WHERE key = ? AND expires_at > ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (key, now),
            ).fetchone()
            if row is None:
                return None
            # Update access tracking
            conn.execute(
                """
                UPDATE shared_context_entries
                SET access_count = access_count + 1, last_accessed = ?
                WHERE id = ?
                """,
                (now, row["id"]),
            )
        return self._row_to_entry(row)

    def get_by_id(self, entry_id: str) -> PersistentContextEntry | None:
        """Retrieve entry by its ID."""
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM shared_context_entries WHERE id = ? AND expires_at > ?",
                (entry_id, now),
            ).fetchone()
            if row is None:
                return None
        return self._row_to_entry(row)

    def list_keys(self, project_id: str | None = None) -> list[str]:
        """List all non-expired keys, optionally filtered by project."""
        now = time.time()
        with self._connect() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT DISTINCT key FROM shared_context_entries WHERE expires_at > ? AND project_id = ?",
                    (now, project_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT key FROM shared_context_entries WHERE expires_at > ?",
                    (now,),
                ).fetchall()
        return [r["key"] for r in rows]

    def list_entries(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
    ) -> list[PersistentContextEntry]:
        """List entries with optional filters."""
        now = time.time()
        conditions = ["expires_at > ?"]
        params: list[Any] = [now]

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)

        where = " AND ".join(conditions)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM shared_context_entries WHERE {where} ORDER BY created_at DESC",
                params,
            ).fetchall()

        entries = [self._row_to_entry(r) for r in rows]

        # Filter by tags in Python (JSON array in SQLite)
        if tags:
            entries = [
                e for e in entries if any(t in e.tags for t in tags)
            ]

        return entries

    def delete(self, key: str) -> bool:
        """Delete all entries for a key. Returns True if any were deleted."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM shared_context_entries WHERE key = ?", (key,)
                )
        return cursor.rowcount > 0

    def clear(self) -> int:
        """Remove all entries. Returns count of entries removed."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM shared_context_entries")
        return cursor.rowcount

    def stats(self, project_id: str | None = None) -> dict[str, Any]:
        """Get aggregate statistics."""
        now = time.time()
        with self._connect() as conn:
            if project_id:
                row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt,
                           COALESCE(SUM(original_tokens), 0) as total_orig,
                           COALESCE(SUM(compressed_tokens), 0) as total_comp
                    FROM shared_context_entries
                    WHERE expires_at > ? AND project_id = ?
                    """,
                    (now, project_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt,
                           COALESCE(SUM(original_tokens), 0) as total_orig,
                           COALESCE(SUM(compressed_tokens), 0) as total_comp
                    FROM shared_context_entries
                    WHERE expires_at > ?
                    """,
                    (now,),
                ).fetchone()

        total_orig = row["total_orig"]
        total_comp = row["total_comp"]
        saved = total_orig - total_comp
        pct = round(saved / total_orig * 100, 1) if total_orig > 0 else 0.0
        return {
            "entries": row["cnt"],
            "total_original_tokens": total_orig,
            "total_compressed_tokens": total_comp,
            "total_tokens_saved": saved,
            "savings_percent": pct,
        }

    def _evict_expired(self, conn: sqlite3.Connection) -> None:
        """Remove expired entries."""
        conn.execute(
            "DELETE FROM shared_context_entries WHERE expires_at <= ?",
            (time.time(),),
        )

    def _evict_lru(self, conn: sqlite3.Connection, count: int) -> None:
        """Remove least-recently-used entries."""
        conn.execute(
            """
            DELETE FROM shared_context_entries
            WHERE id IN (
                SELECT id FROM shared_context_entries
                ORDER BY last_accessed ASC
                LIMIT ?
            )
            """,
            (count,),
        )

    def _row_to_entry(self, row: sqlite3.Row) -> PersistentContextEntry:
        """Convert a database row to a PersistentContextEntry."""
        return PersistentContextEntry(
            id=row["id"],
            key=row["key"],
            content_original=row["content_original"] or "",
            content_compressed=row["content_compressed"] or "",
            agent=row["agent"],
            provider=row["provider"],
            session_id=row["session_id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            original_tokens=row["original_tokens"],
            compressed_tokens=row["compressed_tokens"],
            transforms=json.loads(row["transforms"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            access_count=row["access_count"],
            last_accessed=row["last_accessed"],
            confidence=row["confidence"],
            version=row["version"],
            tags=json.loads(row["tags"]),
        )


def generate_entry_id() -> str:
    """Generate a unique entry ID."""
    return f"sc_{uuid.uuid4().hex[:12]}"
