"""Tool Schema Registry for progressive disclosure.

In-memory registry that indexes all tool schemas and provides
fast lookup by name or semantic query.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ToolEntry:
    """A registered tool with full schema and metadata."""

    id: str
    name: str
    description: str
    schema: dict[str, Any] | None = None
    full_definition: dict[str, Any] = field(default_factory=dict)
    call_count: int = 0
    last_called_at: datetime | None = None
    category: str = ""
    summary: str = ""

    @property
    def token_estimate(self) -> int:
        """Rough token estimate for the full definition."""
        import json
        content = json.dumps(self.full_definition)
        return len(content) // 4


class ToolSchemaRegistry:
    """In-memory registry of all tool schemas for a session.

    Provides:
    - Registration and indexing of tool schemas
    - Name-based lookup
    - Compact summary generation for search
    - Token usage tracking
    """

    def __init__(self) -> None:
        self.tools: dict[str, ToolEntry] = {}
        self.name_index: dict[str, str] = {}  # normalized name -> tool_id
        self.summary_index: dict[str, str] = {}  # tool_id -> compact summary

    def register(self, tool: dict[str, Any]) -> str:
        """Register a tool schema and return its compact ID."""
        name = tool.get("name", "")
        tool_id = f"tool_{hashlib.sha256(name.encode()).hexdigest()[:8]}"

        input_schema = (
            tool.get("input_schema")
            or tool.get("inputSchema")
            or tool.get("function", {}).get("parameters")
        )

        entry = ToolEntry(
            id=tool_id,
            name=name,
            description=tool.get("description", ""),
            schema=input_schema,
            full_definition=tool,
            call_count=0,
            last_called_at=None,
        )
        entry.summary = self._generate_summary(tool)

        self.tools[tool_id] = entry
        self.name_index[name.lower()] = tool_id
        self.summary_index[tool_id] = entry.summary
        return tool_id

    def get_by_name(self, name: str) -> ToolEntry | None:
        """Lookup a tool by exact name (case-insensitive)."""
        tool_id = self.name_index.get(name.lower())
        if tool_id is None:
            return None
        return self.tools.get(tool_id)

    def get_by_id(self, tool_id: str) -> ToolEntry | None:
        """Lookup a tool by its ID."""
        return self.tools.get(tool_id)

    def record_call(self, name: str) -> None:
        """Record that a tool was called (for usage tracking)."""
        entry = self.get_by_name(name)
        if entry:
            entry.call_count += 1
            entry.last_called_at = datetime.now()

    def all_entries(self) -> list[ToolEntry]:
        """Return all registered tool entries."""
        return list(self.tools.values())

    def all_summaries(self) -> list[str]:
        """Return all tool summaries for search indexing."""
        return list(self.summary_index.values())

    @property
    def total_token_estimate(self) -> int:
        """Estimate total tokens for all full schemas."""
        return sum(entry.token_estimate for entry in self.tools.values())

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    def _generate_summary(self, tool: dict[str, Any]) -> str:
        """Generate a compact one-line summary for semantic search."""
        name = tool.get("name", "")
        desc = tool.get("description", "")
        first_sentence = re.split(r"[.!?]\s", desc, maxsplit=1)[0]
        if len(first_sentence) > 120:
            first_sentence = first_sentence[:117] + "..."
        return f"{name}: {first_sentence}"

    def clear(self) -> None:
        """Clear all registered tools."""
        self.tools.clear()
        self.name_index.clear()
        self.summary_index.clear()
