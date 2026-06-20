"""Generic memory writer — exports to plain markdown for any agent.

Fallback writer that produces clean markdown suitable for:
- Aider (via .aider.conf.yml read setting)
- Gemini (GEMINI.md)
- Any agent that reads markdown context files
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from copium.memory.writers.base import AgentWriter, MemoryEntry


class GenericMemoryWriter(AgentWriter):
    """Writes memories to plain markdown format."""

    agent_name = "generic"
    default_token_budget = 3000

    def __init__(
        self,
        project_path: Path | None = None,
        token_budget: int | None = None,
        filename: str = "COPIUM_MEMORY.md",
    ) -> None:
        super().__init__(project_path, token_budget)
        self._filename = filename

    def format_memories(self, memories: list[MemoryEntry]) -> str:
        """Format as clean markdown."""
        lines = [
            "## Copium Learned Context",
            "*Auto-maintained by Copium proxy — do not edit manually*",
            "",
        ]

        grouped: dict[str, list[MemoryEntry]] = defaultdict(list)
        for m in memories:
            cat = m.category or "General"
            heading = cat.replace("_", " ").title()
            grouped[heading].append(m)

        for heading, entries in grouped.items():
            lines.append(f"### {heading}")
            for entry in entries:
                lines.append(f"- {entry.content}")
            lines.append("")

        return "\n".join(lines)

    def default_path(self) -> Path:
        """Default: COPIUM_MEMORY.md in project root."""
        return self._project_path / self._filename
