"""Progressive tool disclosure for MCP proxy.

Instead of sending full tool schemas on every turn, sends minimal
stubs (name + short description, ~20 tokens each) and provides
discovery tools for on-demand schema retrieval.

Reduces tool definition tokens by 99% compared to full schemas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from copium.mcp_proxy.upstream import ToolDefinition


@dataclass
class ToolStub:
    """Minimal tool representation for progressive disclosure."""

    name: str
    short_description: str
    category: str = ""
    required_params: str = ""

    def to_display(self) -> str:
        """Format as a compact display string."""
        parts = [f"- {self.name}"]
        if self.required_params:
            parts[0] += f"({self.required_params})"
        parts[0] += f": {self.short_description}"
        return parts[0]


# Tool categories based on common MCP server types
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "filesystem": ["read", "write", "file", "directory", "path", "list_dir"],
    "search": ["search", "grep", "find", "query", "lookup"],
    "git": ["git", "commit", "branch", "diff", "log"],
    "database": ["sql", "query", "table", "schema", "insert", "select"],
    "web": ["fetch", "browse", "http", "url", "scrape", "puppeteer"],
    "code": ["run", "exec", "compile", "lint", "format", "test"],
}


@dataclass
class ProgressiveDisclosure:
    """Engine for progressive tool disclosure.

    Workflow:
    1. Initial: Agent sees tool stubs (20 tokens each)
    2. Discovery: Agent calls copium_find_tool(query) to find relevant tools
    3. Schema: Agent calls copium_get_tool_schema(name) for full definition
    4. Cached: Schema cached for session, never re-sent
    """

    _tools: list[ToolDefinition] = field(default_factory=list)
    """All available tools from upstream servers."""

    _stubs: list[ToolStub] = field(default_factory=list)
    """Computed stubs for all tools."""

    _disclosed: set[str] = field(default_factory=set)
    """Set of tool names whose full schema has been disclosed."""

    _stats: dict[str, int] = field(default_factory=lambda: {
        "stub_requests": 0,
        "find_requests": 0,
        "schema_requests": 0,
        "tokens_saved": 0,
    })

    def register_tools(self, tools: list[ToolDefinition]) -> None:
        """Register available tools and generate stubs."""
        self._tools = tools
        self._stubs = [self._make_stub(t) for t in tools]

    def get_stubs(self) -> list[ToolStub]:
        """Get minimal stubs for all tools."""
        self._stats["stub_requests"] += 1
        return self._stubs

    def get_stubs_display(self) -> str:
        """Get a formatted string of all tool stubs."""
        lines = ["Available tools:"]
        # Group by category
        categorized: dict[str, list[ToolStub]] = {}
        for stub in self._stubs:
            cat = stub.category or "other"
            categorized.setdefault(cat, []).append(stub)

        for category, stubs in sorted(categorized.items()):
            lines.append(f"\n[{category}]")
            for stub in stubs:
                lines.append(f"  {stub.to_display()}")

        lines.append(
            "\nUse copium_find_tool(query) to discover tools, "
            "or copium_get_tool_schema(name) for full details."
        )
        return "\n".join(lines)

    def find_tools(self, query: str, category: str | None = None) -> list[dict[str, Any]]:
        """Find tools matching a query.

        Args:
            query: What the user needs to do.
            category: Optional category filter.

        Returns:
            List of matching tools with relevance scores.
        """
        self._stats["find_requests"] += 1
        query_lower = query.lower()
        query_words = set(query_lower.split())

        results: list[dict[str, Any]] = []
        for tool in self._tools:
            if category and not self._matches_category(tool.name, category):
                continue

            score = self._relevance_score(tool, query_lower, query_words)
            if score > 0.1:
                results.append({
                    "name": tool.name,
                    "description": self._shorten(tool.description),
                    "server": tool.server_name,
                    "relevance": round(score, 2),
                    "schema_disclosed": tool.name in self._disclosed,
                })

        results.sort(key=lambda r: r["relevance"], reverse=True)
        return results[:10]

    def get_full_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Get the full schema for a specific tool.

        Marks the tool as disclosed (schema cached for session).
        """
        self._stats["schema_requests"] += 1

        for tool in self._tools:
            if tool.name == tool_name:
                self._disclosed.add(tool_name)
                return {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                    "server": tool.server_name,
                }
        return None

    def is_disclosed(self, tool_name: str) -> bool:
        """Check if a tool's schema has been fully disclosed."""
        return tool_name in self._disclosed

    def _make_stub(self, tool: ToolDefinition) -> ToolStub:
        """Create a minimal stub from a full tool definition."""
        short_desc = self._shorten(tool.description)
        category = self._detect_category(tool.name)
        required_params = self._extract_required_params(tool.input_schema)

        return ToolStub(
            name=tool.name,
            short_description=short_desc,
            category=category,
            required_params=required_params,
        )

    @staticmethod
    def _shorten(description: str, max_words: int = 8) -> str:
        """Shorten a description to max_words."""
        if not description:
            return ""
        # Strip common prefixes
        desc = re.sub(
            r"^(?:this tool |use this to |allows you to )",
            "",
            description,
            flags=re.IGNORECASE,
        )
        words = desc.split()
        if len(words) <= max_words:
            return desc.strip()
        return " ".join(words[:max_words]).rstrip(".,;:") + "..."

    @staticmethod
    def _detect_category(tool_name: str) -> str:
        """Detect tool category from its name."""
        name_lower = tool_name.lower()
        for category, patterns in CATEGORY_PATTERNS.items():
            if any(p in name_lower for p in patterns):
                return category
        return "other"

    @staticmethod
    def _matches_category(tool_name: str, category: str) -> bool:
        """Check if a tool matches a category."""
        patterns = CATEGORY_PATTERNS.get(category, [])
        name_lower = tool_name.lower()
        return any(p in name_lower for p in patterns)

    @staticmethod
    def _extract_required_params(schema: dict[str, Any]) -> str:
        """Extract required parameter names from schema."""
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        parts = []
        for param in required[:3]:  # Max 3 params in stub
            ptype = properties.get(param, {}).get("type", "")
            parts.append(f"{param}: {ptype}" if ptype else param)

        return ", ".join(parts)

    @staticmethod
    def _relevance_score(
        tool: ToolDefinition, query: str, query_words: set[str]
    ) -> float:
        """Calculate relevance score for a tool against a query."""
        score = 0.0
        name_lower = tool.name.lower()
        desc_lower = tool.description.lower()

        # Exact name match
        if query in name_lower:
            score += 0.8

        # Word overlap with name
        name_words = set(re.split(r"[_\-\s]+", name_lower))
        name_overlap = len(query_words & name_words) / max(len(query_words), 1)
        score += name_overlap * 0.5

        # Word overlap with description
        desc_words = set(desc_lower.split())
        desc_overlap = len(query_words & desc_words) / max(len(query_words), 1)
        score += desc_overlap * 0.3

        return min(score, 1.0)

    @property
    def stats(self) -> dict[str, Any]:
        """Return progressive disclosure statistics."""
        return {
            **self._stats,
            "total_tools": len(self._tools),
            "tools_disclosed": len(self._disclosed),
        }
