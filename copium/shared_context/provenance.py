"""Agent provenance tracking for SharedContext.

Tracks which agent created, modified, or accessed each context entry.
Provides agent identity, versioning, and confidence scoring.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentIdentity:
    """Identifies an agent that interacts with shared context.

    Captures enough information to trace context back to its source
    across frameworks, providers, and sessions.
    """

    agent_name: str
    provider: str | None = None  # anthropic, openai, google, etc.
    model: str | None = None  # claude-sonnet-4-5-20250929, gpt-4o, etc.
    session_id: str | None = None
    user_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentIdentity:
        return cls(
            agent_name=data.get("agent_name", "unknown"),
            provider=data.get("provider"),
            model=data.get("model"),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> AgentIdentity:
        """Extract agent identity from HTTP request headers.

        Expected headers:
            X-Copium-Agent: agent name
            X-Copium-Agent-Provider: provider name
            X-Copium-Agent-Model: model name
            X-Copium-Session-Id: session id
            X-Copium-User-Id: user id
        """
        return cls(
            agent_name=headers.get("x-copium-agent", "unknown"),
            provider=headers.get("x-copium-agent-provider"),
            model=headers.get("x-copium-agent-model"),
            session_id=headers.get("x-copium-session-id"),
            user_id=headers.get("x-copium-user-id"),
        )


@dataclass
class ContextProvenance:
    """Full provenance record for a shared context entry.

    Tracks creation, modifications, and access patterns.
    """

    entry_id: str
    created_by: AgentIdentity
    last_modified_by: AgentIdentity
    version: int = 1
    superseded_by: str | None = None
    confidence: float = 0.9
    source_session: str | None = None
    source_turn: int | None = None
    tags: list[str] = field(default_factory=list)
    access_log: list[AccessRecord] = field(default_factory=list)

    def record_access(self, agent: AgentIdentity) -> None:
        """Record that an agent accessed this entry."""
        self.access_log.append(AccessRecord(agent=agent, timestamp=time.time()))

    def record_modification(self, agent: AgentIdentity) -> None:
        """Record a modification, incrementing version."""
        self.version += 1
        self.last_modified_by = agent

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "created_by": self.created_by.to_dict(),
            "last_modified_by": self.last_modified_by.to_dict(),
            "version": self.version,
            "superseded_by": self.superseded_by,
            "confidence": self.confidence,
            "source_session": self.source_session,
            "source_turn": self.source_turn,
            "tags": self.tags,
            "access_count": len(self.access_log),
        }

    @classmethod
    def create(
        cls,
        entry_id: str,
        agent: AgentIdentity,
        *,
        confidence: float = 0.9,
        tags: list[str] | None = None,
        session_id: str | None = None,
        turn: int | None = None,
    ) -> ContextProvenance:
        """Create a new provenance record."""
        return cls(
            entry_id=entry_id,
            created_by=agent,
            last_modified_by=agent,
            version=1,
            confidence=confidence,
            source_session=session_id or agent.session_id,
            source_turn=turn,
            tags=tags or [],
        )


@dataclass
class AccessRecord:
    """A record of an agent accessing a shared context entry."""

    agent: AgentIdentity
    timestamp: float = field(default_factory=time.time)
    action: str = "read"  # read, write, search
