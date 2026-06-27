"""Tests for enhanced MCP proxy with progressive disclosure."""

from __future__ import annotations

import pytest

from copium.proxy.mcp_enhanced import (
    DisclosureMetrics,
    ProgressiveDisclosure,
    ToolRegistry,
    ToolSchema,
    ToolStub,
)
from copium.proxy.tool_compressor import CompressedTool, ToolDescriptionCompressor


# =============================================================================
# ToolRegistry Tests
# =============================================================================


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def setup_method(self):
        self.registry = ToolRegistry()
        self.registry.register(
            ToolSchema(
                name="read_file",
                description="Read the contents of a file from the filesystem.",
                parameters={"path": {"type": "string", "description": "File path"}},
            ),
            category="filesystem",
        )
        self.registry.register(
            ToolSchema(
                name="write_file",
                description="Write content to a file on the filesystem.",
                parameters={
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content to write"},
                },
            ),
            category="filesystem",
        )
        self.registry.register(
            ToolSchema(
                name="search_code",
                description="Search for code patterns using regex across the codebase.",
                parameters={"pattern": {"type": "string", "description": "Regex pattern"}},
            ),
            category="search",
        )

    def test_register_and_count(self):
        assert self.registry.tool_count == 3

    def test_get_schema(self):
        schema = self.registry.get_schema("read_file")
        assert schema is not None
        assert schema.name == "read_file"
        assert "path" in schema.parameters

    def test_get_stub(self):
        stub = self.registry.get_stub("read_file")
        assert stub is not None
        assert stub.name == "read_file"
        # Stub description should be <= original (first sentence or truncated)
        assert len(stub.short_description) <= len(
            "Read the contents of a file from the filesystem."
        )

    def test_all_stubs(self):
        stubs = self.registry.all_stubs()
        assert len(stubs) == 3

    def test_search_exact_name(self):
        results = self.registry.search("read_file")
        assert len(results) > 0
        assert results[0].name == "read_file"

    def test_search_keyword(self):
        results = self.registry.search("file")
        assert len(results) >= 2
        names = [r.name for r in results]
        assert "read_file" in names
        assert "write_file" in names

    def test_search_category(self):
        results = self.registry.search("search")
        assert any(r.name == "search_code" for r in results)

    def test_search_no_match(self):
        results = self.registry.search("nonexistent_xyz_123")
        assert len(results) == 0

    def test_by_category(self):
        fs_tools = self.registry.by_category("filesystem")
        assert len(fs_tools) == 2
        names = [t.name for t in fs_tools]
        assert "read_file" in names
        assert "write_file" in names


# =============================================================================
# ProgressiveDisclosure Tests
# =============================================================================


class TestProgressiveDisclosure:
    """Tests for progressive tool disclosure."""

    def setup_method(self):
        self.registry = ToolRegistry()
        for i in range(20):
            self.registry.register(
                ToolSchema(
                    name=f"tool_{i}",
                    description=f"This is tool number {i} with a detailed description "
                    f"that explains what it does and how to use it with examples.",
                    parameters={
                        "arg1": {"type": "string", "description": f"First argument for tool {i}"},
                        "arg2": {"type": "integer", "description": f"Second argument for tool {i}"},
                    },
                ),
                category=f"category_{i % 4}",
            )
        self.disclosure = ProgressiveDisclosure(self.registry)

    def test_initial_list_returns_stubs(self):
        stubs = self.disclosure.get_initial_tool_list()
        assert len(stubs) == 20
        # Stubs should be much smaller than full schemas
        assert all(isinstance(s, ToolStub) for s in stubs)

    def test_token_savings(self):
        self.disclosure.get_initial_tool_list()
        metrics = self.disclosure.metrics
        assert metrics.tokens_disclosed < metrics.tokens_full_schema
        assert metrics.savings_pct > 0

    def test_find_tools_returns_relevant(self):
        results = self.disclosure.find_tools("tool_5")
        assert len(results) > 0
        assert results[0].name == "tool_5"

    def test_disclose_schema(self):
        schema = self.disclosure.disclose_schema("tool_0")
        assert schema is not None
        assert schema.name == "tool_0"
        assert "arg1" in schema.parameters

    def test_is_disclosed_tracking(self):
        assert not self.disclosure.is_disclosed("tool_0")
        self.disclosure.disclose_schema("tool_0")
        assert self.disclosure.is_disclosed("tool_0")
        assert not self.disclosure.is_disclosed("tool_1")

    def test_reset(self):
        self.disclosure.disclose_schema("tool_0")
        assert self.disclosure.is_disclosed("tool_0")
        self.disclosure.reset()
        assert not self.disclosure.is_disclosed("tool_0")

    def test_nonexistent_tool(self):
        schema = self.disclosure.disclose_schema("nonexistent")
        assert schema is None


# =============================================================================
# ToolDescriptionCompressor Tests
# =============================================================================


class TestToolDescriptionCompressor:
    """Tests for tool description compression."""

    def test_strips_verbose_prefix(self):
        compressor = ToolDescriptionCompressor(aggressiveness=0.5)
        tool = {
            "name": "read_file",
            "description": "This tool is used to read the contents of a file.",
            "inputSchema": {},
        }
        result = compressor.compress_tool(tool)
        assert "This tool is used to" not in result.description
        assert "read" in result.description.lower()

    def test_preserves_with_low_aggressiveness(self):
        compressor = ToolDescriptionCompressor(aggressiveness=0.1)
        tool = {
            "name": "test",
            "description": "A simple test description.",
            "inputSchema": {},
        }
        result = compressor.compress_tool(tool)
        # Low aggressiveness should mostly preserve
        assert len(result.description) >= len("A simple test description.") - 10

    def test_abbreviations_at_medium(self):
        compressor = ToolDescriptionCompressor(aggressiveness=0.5)
        tool = {
            "name": "test",
            "description": "This function returns a list of required parameters.",
            "inputSchema": {},
        }
        result = compressor.compress_tool(tool)
        # Should apply some abbreviations
        assert result.compressed_tokens <= result.original_tokens

    def test_removes_examples_at_high(self):
        compressor = ToolDescriptionCompressor(aggressiveness=0.8)
        tool = {
            "name": "test",
            "description": "Do something useful.\n\nExample: test('hello')\nMore text.",
            "inputSchema": {},
        }
        result = compressor.compress_tool(tool)
        assert "Example" not in result.description

    def test_compress_batch(self):
        compressor = ToolDescriptionCompressor(aggressiveness=0.5)
        tools = [
            {"name": f"tool_{i}", "description": f"This tool does thing {i}.", "inputSchema": {}}
            for i in range(5)
        ]
        results = compressor.compress_batch(tools)
        assert len(results) == 5
        assert all(isinstance(r, CompressedTool) for r in results)

    def test_parameter_compression(self):
        compressor = ToolDescriptionCompressor(aggressiveness=0.7)
        tool = {
            "name": "complex_tool",
            "description": "A complex tool.",
            "inputSchema": {
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to read. For example, /tmp/test.txt",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["read", "write"],
                        "description": "The mode to open the file in.",
                    },
                },
            },
        }
        result = compressor.compress_tool(tool)
        # Parameters should be compressed
        assert result.compressed_tokens <= result.original_tokens
