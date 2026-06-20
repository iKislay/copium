"""Agent-native memory writers — export Copium memories to each agent's format.

Each writer knows how to produce memory files in the format that a specific
coding agent reads on startup. Writers handle:
- Format constraints (YAML frontmatter, heading levels, line limits)
- Token budget management (prioritize by importance × recency)
- Deduplication against existing content
- Marker-delimited sections for safe updates

Supported agents:
- Claude Code: MEMORY.md (auto-memory) + per-topic files
- Cursor: .cursor/rules/*.mdc (YAML frontmatter + markdown)
- Codex: AGENTS.md / ~/.codex/instructions.md
- Aider: Convention files referenced in .aider.conf.yml
- Gemini: GEMINI.md
- Generic: Plain markdown (any agent)
"""

from copium.memory.writers.base import AgentWriter, ExportResult, MemoryEntry
from copium.memory.writers.claude_writer import ClaudeCodeMemoryWriter
from copium.memory.writers.codex_writer import CodexMemoryWriter
from copium.memory.writers.cursor_writer import CursorMemoryWriter
from copium.memory.writers.generic_writer import GenericMemoryWriter

__all__ = [
    "AgentWriter",
    "ClaudeCodeMemoryWriter",
    "CodexMemoryWriter",
    "CursorMemoryWriter",
    "ExportResult",
    "GenericMemoryWriter",
    "MemoryEntry",
]
