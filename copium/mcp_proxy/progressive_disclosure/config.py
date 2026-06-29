"""Configuration for progressive tool disclosure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ProgressiveDisclosureConfig:
    """Configuration for the progressive tool disclosure system."""

    enabled: bool = True
    """Enable progressive tool disclosure."""

    eager_load_max: int = 10
    """Maximum number of tools to load eagerly."""

    search_backend: Literal["bm25", "keyword"] = "bm25"
    """Search backend for tool discovery. 'bm25' is recommended."""

    search_top_k: int = 3
    """Number of tools to return from find_tool queries."""

    eager_patterns: list[str] = field(default_factory=lambda: [
        "read_file", "write_file", "list_dir", "search_files",
        "search", "grep", "find", "glob",
        "run_command", "execute", "bash",
    ])
    """Tool name patterns that should always be loaded eagerly."""

    eager_prefixes: list[str] = field(default_factory=lambda: [
        "copium_",
    ])
    """Tool name prefixes that should always be loaded eagerly."""

    min_tools_for_disclosure: int = 8
    """Minimum number of tools before progressive disclosure activates."""

    cache_schemas: bool = True
    """Cache resolved schemas for repeated lookups."""

    inject_system_prompt: bool = True
    """Inject system prompt fragment to teach LLM the pattern."""
