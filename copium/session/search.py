"""Session search — FTS5-powered full-text search across session archives.

Builds a lightweight SQLite index of session content for fast searching
across all agent session archives (Claude Code, Cursor, Aider, etc.).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .archive import SessionArchive, SessionMessage

logger = logging.getLogger(__name__)

# Default index location
DEFAULT_INDEX_PATH = Path.home() / ".copium" / "session_index.db"


@dataclass
class SearchResult:
    """A single search result from the session index."""

    session_path: str
    turn_index: int
    role: str
    content_snippet: str
    score: float
    agent: str = ""
    timestamp: str = ""


@dataclass
class SearchConfig:
    """Configuration for session search."""

    index_path: Path = field(default_factory=lambda: DEFAULT_INDEX_PATH)
    max_results: int = 20
    snippet_length: int = 200


class SessionSearch:
    """FTS5-powered search across all indexed session archives."""

    def __init__(self, config: SearchConfig | None = None):
        self.config = config or SearchConfig()
        self._db: sqlite3.Connection | None = None
        self._ensure_schema()

    def _get_db(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._db is None:
            self.config.index_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self.config.index_path))
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
        return self._db

    def _ensure_schema(self) -> None:
        """Create tables and FTS5 index if they don't exist."""
        db = self._get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                agent TEXT NOT NULL DEFAULT '',
                indexed_at REAL NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                token_estimate INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                turn_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                timestamp TEXT DEFAULT '',
                UNIQUE(session_id, turn_index, role)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                content='messages',
                content_rowid='id',
                tokenize='porter unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END;
        """)
        db.commit()

    def index_session(
        self, path: Path, agent: str = "", messages: list[SessionMessage] | None = None
    ) -> int:
        """Index a session archive for searching.

        Args:
            path: Path to the session file.
            agent: Agent name (claude_code, cursor, aider, opencode).
            messages: Pre-parsed messages. If None, parses from path.

        Returns:
            Number of messages indexed.
        """
        db = self._get_db()

        # Check if already indexed (skip re-index if file hasn't changed)
        existing = db.execute(
            "SELECT id, indexed_at FROM sessions WHERE path = ?", (str(path),)
        ).fetchone()

        if existing and path.exists():
            file_mtime = path.stat().st_mtime
            if file_mtime <= existing[1]:
                return 0  # Already up-to-date

            # Remove old index
            db.execute("DELETE FROM messages WHERE session_id = ?", (existing[0],))
            db.execute("DELETE FROM sessions WHERE id = ?", (existing[0],))

        # Parse if needed
        if messages is None:
            archive = SessionArchive(path)
            messages = archive.messages

        if not messages:
            return 0

        # Insert session record
        token_est = sum(len(m.content) for m in messages) // 4
        cursor = db.execute(
            "INSERT INTO sessions (path, agent, indexed_at, message_count, token_estimate) VALUES (?, ?, ?, ?, ?)",
            (str(path), agent, time.time(), len(messages), token_est),
        )
        session_id = cursor.lastrowid

        # Insert messages
        for msg in messages:
            if not msg.content.strip():
                continue
            timestamp = msg.metadata.get("timestamp", "")
            db.execute(
                "INSERT OR IGNORE INTO messages (session_id, turn_index, role, type, content, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, msg.turn_index, msg.role, msg.type, msg.content, str(timestamp)),
            )

        db.commit()
        logger.info("Indexed %d messages from %s (%s)", len(messages), path, agent)
        return len(messages)

    def search(
        self,
        query: str,
        *,
        agent: str | None = None,
        role: str | None = None,
        max_results: int | None = None,
    ) -> list[SearchResult]:
        """Search across all indexed sessions.

        Args:
            query: FTS5 search query (supports AND, OR, NOT, phrases).
            agent: Filter by agent name.
            role: Filter by message role (user, assistant, tool).
            max_results: Override default max results.

        Returns:
            List of SearchResult ordered by relevance.
        """
        db = self._get_db()
        limit = max_results or self.config.max_results

        # Build query
        sql = """
            SELECT
                s.path,
                m.turn_index,
                m.role,
                snippet(messages_fts, 0, '>>>', '<<<', '...', 64) as snippet,
                rank,
                s.agent,
                m.timestamp
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE messages_fts MATCH ?
        """
        params: list[Any] = [query]

        if agent:
            sql += " AND s.agent = ?"
            params.append(agent)

        if role:
            sql += " AND m.role = ?"
            params.append(role)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        results: list[SearchResult] = []
        try:
            for row in db.execute(sql, params):
                results.append(
                    SearchResult(
                        session_path=row[0],
                        turn_index=row[1],
                        role=row[2],
                        content_snippet=row[3],
                        score=abs(row[4]),  # FTS5 rank is negative
                        agent=row[5],
                        timestamp=row[6],
                    )
                )
        except sqlite3.OperationalError as e:
            logger.warning("Search query failed: %s", e)

        return results

    def search_file(self, file_path: str, *, agent: str | None = None) -> list[SearchResult]:
        """Find sessions where a specific file was referenced.

        Args:
            file_path: File path to search for (partial match).
            agent: Optional agent filter.

        Returns:
            Sessions referencing the file.
        """
        # Use FTS5 with quoted phrase for file path
        escaped = file_path.replace('"', '""')
        return self.search(f'"{escaped}"', agent=agent)

    def get_session_summary(self, path: Path) -> dict[str, Any] | None:
        """Get summary info for an indexed session."""
        db = self._get_db()
        row = db.execute(
            "SELECT id, agent, indexed_at, message_count, token_estimate FROM sessions WHERE path = ?",
            (str(path),),
        ).fetchone()

        if not row:
            return None

        return {
            "path": str(path),
            "agent": row[1],
            "indexed_at": row[2],
            "message_count": row[3],
            "token_estimate": row[4],
        }

    def index_directory(
        self, directory: Path, *, agent: str = "", recursive: bool = True
    ) -> int:
        """Index all session files in a directory.

        Auto-detects agent format for each file.
        """
        from .adapters import detect_adapter

        pattern = "**/*" if recursive else "*"
        total_indexed = 0

        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            if path.suffix not in (".jsonl", ".json", ".md"):
                continue

            # Auto-detect agent
            detected_agent = agent
            if not detected_agent:
                adapter = detect_adapter(path)
                if adapter:
                    detected_agent = adapter.name

            try:
                count = self.index_session(path, agent=detected_agent)
                total_indexed += count
            except Exception as e:
                logger.warning("Failed to index %s: %s", path, e)

        return total_indexed

    def stats(self) -> dict[str, Any]:
        """Get index statistics."""
        db = self._get_db()
        session_count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        message_count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        total_tokens = db.execute(
            "SELECT COALESCE(SUM(token_estimate), 0) FROM sessions"
        ).fetchone()[0]

        agent_counts = {}
        for row in db.execute(
            "SELECT agent, COUNT(*) FROM sessions GROUP BY agent"
        ):
            agent_counts[row[0] or "unknown"] = row[1]

        return {
            "sessions": session_count,
            "messages": message_count,
            "total_tokens_est": total_tokens,
            "agents": agent_counts,
            "index_path": str(self.config.index_path),
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None
