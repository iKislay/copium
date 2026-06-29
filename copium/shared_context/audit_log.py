"""Audit log for SharedContext operations.

Records all put/get/delete/search operations for full traceability.
Useful for enterprise compliance and debugging multi-agent workflows.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditAction(Enum):
    """Types of auditable actions."""

    PUT = "put"
    GET = "get"
    GET_FULL = "get_full"
    SEARCH = "search"
    DELETE = "delete"
    CONFLICT = "conflict"
    EVICT = "evict"
    MERGE = "merge"


@dataclass
class AuditRecord:
    """A single audit log entry."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    action: AuditAction = AuditAction.GET
    entry_key: str = ""
    entry_id: str | None = None
    agent_name: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "entry_key": self.entry_key,
            "entry_id": self.entry_id,
            "agent_name": self.agent_name,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "details": self.details,
        }


class AuditLog:
    """SQLite-backed audit log for SharedContext operations.

    Records all operations with agent identity, timestamps, and
    action-specific details. Supports querying by time range,
    agent, and action type.

    Args:
        db_path: Path to audit log database. Defaults to ~/.copium/audit.db.
        enabled: Whether audit logging is enabled (default: True).
        max_records: Maximum records to retain (older are pruned).
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        enabled: bool = True,
        max_records: int = 100_000,
    ) -> None:
        self._enabled = enabled
        self._max_records = max_records
        self._lock = threading.Lock()

        if db_path is None:
            audit_dir = Path.home() / ".copium"
            audit_dir.mkdir(parents=True, exist_ok=True)
            db_path = audit_dir / "shared_context_audit.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        if self._enabled:
            self._init_db()

    def _init_db(self) -> None:
        """Create audit table."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    entry_key TEXT NOT NULL,
                    entry_id TEXT,
                    agent_name TEXT,
                    session_id TEXT,
                    user_id TEXT,
                    details TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                    ON audit_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_action
                    ON audit_log(action);
                CREATE INDEX IF NOT EXISTS idx_audit_agent
                    ON audit_log(agent_name);
                CREATE INDEX IF NOT EXISTS idx_audit_entry_key
                    ON audit_log(entry_key);
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, audit: AuditRecord) -> None:
        """Record an audit event."""
        if not self._enabled:
            return

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log
                    (id, timestamp, action, entry_key, entry_id,
                     agent_name, session_id, user_id, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit.id,
                        audit.timestamp,
                        audit.action.value,
                        audit.entry_key,
                        audit.entry_id,
                        audit.agent_name,
                        audit.session_id,
                        audit.user_id,
                        json.dumps(audit.details),
                    ),
                )
                self._prune_if_needed(conn)

    def query(
        self,
        *,
        action: AuditAction | None = None,
        agent_name: str | None = None,
        entry_key: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        """Query audit records with filters."""
        if not self._enabled:
            return []

        conditions = []
        params: list[Any] = []

        if action:
            conditions.append("action = ?")
            params.append(action.value)
        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if entry_key:
            conditions.append("entry_key = ?")
            params.append(entry_key)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()

        return [self._row_to_record(r) for r in rows]

    def count(self, *, since: float | None = None) -> int:
        """Count total audit records, optionally since a timestamp."""
        if not self._enabled:
            return 0

        with self._connect() as conn:
            if since:
                row = conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE timestamp >= ?",
                    (since,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        return row[0]

    def clear(self) -> int:
        """Clear all audit records. Returns count removed."""
        if not self._enabled:
            return 0

        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM audit_log")
        return cursor.rowcount

    def _prune_if_needed(self, conn: sqlite3.Connection) -> None:
        """Remove oldest records if over capacity."""
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        if count > self._max_records:
            excess = count - self._max_records
            conn.execute(
                """
                DELETE FROM audit_log WHERE id IN (
                    SELECT id FROM audit_log ORDER BY timestamp ASC LIMIT ?
                )
                """,
                (excess,),
            )

    def _row_to_record(self, row: sqlite3.Row) -> AuditRecord:
        return AuditRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            action=AuditAction(row["action"]),
            entry_key=row["entry_key"],
            entry_id=row["entry_id"],
            agent_name=row["agent_name"],
            session_id=row["session_id"],
            user_id=row["user_id"],
            details=json.loads(row["details"]) if row["details"] else {},
        )
