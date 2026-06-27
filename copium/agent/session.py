"""Session persistence for agent workflows.

Save and restore compressed agent sessions, enabling:
- Session continuation across process restarts
- Session branching (fork from a point)
- Session sharing between agents
- Compressed storage (sessions stored in compressed form)

ContextCrumb has no session management. This is unique to Copium.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CompressedSession:
    """A compressed agent session."""

    session_id: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    total_turns: int = 0
    compressed_tokens: int = 0
    original_tokens: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens == 0:
            return 1.0
        return self.compressed_tokens / self.original_tokens

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "session_id": self.session_id,
            "messages": self.messages,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_turns": self.total_turns,
            "compressed_tokens": self.compressed_tokens,
            "original_tokens": self.original_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompressedSession:
        """Deserialize from dictionary."""
        return cls(
            session_id=data["session_id"],
            messages=data.get("messages", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            total_turns=data.get("total_turns", 0),
            compressed_tokens=data.get("compressed_tokens", 0),
            original_tokens=data.get("original_tokens", 0),
        )


class SessionStore:
    """Persistent storage for compressed agent sessions.

    Stores sessions as compressed JSON files on disk, enabling
    session save/restore across process restarts.
    """

    def __init__(self, storage_dir: Path | str | None = None):
        """Initialize session store.

        Args:
            storage_dir: Directory for session files. Defaults to ~/.copium/sessions/
        """
        if storage_dir is None:
            storage_dir = Path.home() / ".copium" / "sessions"
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, CompressedSession] = {}

    def save(self, session: CompressedSession) -> str:
        """Save a session to disk.

        Args:
            session: Session to save.

        Returns:
            Session ID.
        """
        session.updated_at = time.time()
        self._sessions[session.session_id] = session

        # Write to disk
        path = self._session_path(session.session_id)
        path.write_text(json.dumps(session.to_dict(), indent=2))

        logger.debug(
            "Saved session %s (%d turns, %d tokens)",
            session.session_id,
            session.total_turns,
            session.compressed_tokens,
        )
        return session.session_id

    def load(self, session_id: str) -> CompressedSession | None:
        """Load a session from disk.

        Args:
            session_id: Session ID to load.

        Returns:
            CompressedSession or None if not found.
        """
        # Check memory cache first
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Check disk
        path = self._session_path(session_id)
        if not path.exists():
            return None

        data = json.loads(path.read_text())
        session = CompressedSession.from_dict(data)
        self._sessions[session_id] = session
        return session

    def list_sessions(self) -> list[CompressedSession]:
        """List all stored sessions.

        Returns:
            List of sessions sorted by most recent first.
        """
        sessions: list[CompressedSession] = []
        for path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                sessions.append(CompressedSession.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                logger.warning("Skipping corrupt session file: %s", path)
                continue

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session to delete.

        Returns:
            True if deleted, False if not found.
        """
        self._sessions.pop(session_id, None)
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def create_session(
        self,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> CompressedSession:
        """Create a new session from messages.

        Args:
            messages: Initial messages for the session.
            metadata: Optional session metadata.

        Returns:
            New CompressedSession.
        """
        content_hash = hashlib.sha256(
            json.dumps(messages, sort_keys=True).encode()
        ).hexdigest()[:12]
        session_id = f"session_{int(time.time())}_{content_hash}"

        tokens = sum(len(str(m.get("content", ""))) // 4 for m in messages)

        session = CompressedSession(
            session_id=session_id,
            messages=messages,
            metadata=metadata or {},
            total_turns=len([m for m in messages if m.get("role") == "user"]),
            compressed_tokens=tokens,
            original_tokens=tokens,
        )

        return session

    def fork_session(
        self, session_id: str, at_turn: int | None = None
    ) -> CompressedSession | None:
        """Fork a session at a specific turn.

        Creates a new session branching from the specified point,
        enabling exploration of alternative paths.

        Args:
            session_id: Session to fork from.
            at_turn: Turn number to fork at (None = latest).

        Returns:
            New forked session or None if source not found.
        """
        source = self.load(session_id)
        if source is None:
            return None

        # Truncate messages to the fork point
        if at_turn is not None:
            user_turns_seen = 0
            fork_idx = len(source.messages)
            for i, msg in enumerate(source.messages):
                if msg.get("role") == "user":
                    user_turns_seen += 1
                    if user_turns_seen > at_turn:
                        fork_idx = i
                        break
            messages = source.messages[:fork_idx]
        else:
            messages = list(source.messages)

        forked = self.create_session(
            messages=messages,
            metadata={
                **source.metadata,
                "forked_from": session_id,
                "fork_turn": at_turn,
            },
        )
        return forked

    def _session_path(self, session_id: str) -> Path:
        """Get filesystem path for a session."""
        # Sanitize session_id to prevent path traversal
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "_-")
        return self._storage_dir / f"{safe_id}.json"
