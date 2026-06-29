"""Tests for the MCP proxy progressive disclosure and response compressor."""

from __future__ import annotations

from copium.mcp_proxy.progressive import ProgressiveDisclosure
from copium.mcp_proxy.response_compressor import ResponseCompressor
from copium.mcp_proxy.schema_compressor import SchemaCompressor
from copium.mcp_proxy.upstream import ToolDefinition


class TestProgressiveDisclosure:
    """Test suite for ProgressiveDisclosure."""

    def setup_method(self):
        self.disclosure = ProgressiveDisclosure()
        self.tools = [
            ToolDefinition(
                name="read_file",
                description="Read the complete contents of a file from the filesystem.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                    },
                    "required": ["path"],
                },
                server_name="filesystem",
            ),
            ToolDefinition(
                name="search_code",
                description="Search for patterns in source code files.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["query"],
                },
                server_name="filesystem",
            ),
            ToolDefinition(
                name="git_log",
                description="Show commit history for a repository.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                    },
                },
                server_name="git",
            ),
        ]
        self.disclosure.register_tools(self.tools)

    def test_stubs_generated(self):
        """Tool stubs should be generated for all tools."""
        stubs = self.disclosure.get_stubs()
        assert len(stubs) == 3
        assert stubs[0].name == "read_file"

    def test_stubs_are_compact(self):
        """Stub descriptions should be short."""
        stubs = self.disclosure.get_stubs()
        for stub in stubs:
            words = stub.short_description.split()
            assert len(words) <= 10

    def test_category_detection(self):
        """Tools should be assigned correct categories."""
        stubs = self.disclosure.get_stubs()
        names_to_cats = {s.name: s.category for s in stubs}
        assert names_to_cats["read_file"] == "filesystem"
        assert names_to_cats["search_code"] == "search"
        assert names_to_cats["git_log"] == "git"

    def test_find_tools_by_query(self):
        """find_tools should return relevant tools."""
        results = self.disclosure.find_tools("read file")
        assert len(results) > 0
        assert results[0]["name"] == "read_file"

    def test_find_tools_with_category(self):
        """find_tools with category should filter."""
        results = self.disclosure.find_tools("show history", category="git")
        # Should only return git tools
        for r in results:
            tool_def = next(t for t in self.tools if t.name == r["name"])
            assert tool_def.server_name == "git"

    def test_get_full_schema(self):
        """get_full_schema should return full tool definition."""
        schema = self.disclosure.get_full_schema("read_file")
        assert schema is not None
        assert schema["name"] == "read_file"
        assert "inputSchema" in schema

    def test_get_full_schema_marks_disclosed(self):
        """Getting full schema should mark tool as disclosed."""
        assert not self.disclosure.is_disclosed("read_file")
        self.disclosure.get_full_schema("read_file")
        assert self.disclosure.is_disclosed("read_file")

    def test_get_full_schema_unknown_tool(self):
        """Unknown tool should return None."""
        assert self.disclosure.get_full_schema("nonexistent") is None

    def test_stubs_display(self):
        """Stubs display should be a formatted string."""
        display = self.disclosure.get_stubs_display()
        assert "Available tools:" in display
        assert "read_file" in display
        assert "copium_find_tool" in display


class TestResponseCompressor:
    """Test suite for ResponseCompressor."""

    def setup_method(self):
        self.compressor = ResponseCompressor(min_tokens_to_compress=10)

    def test_small_responses_pass_through(self):
        """Responses below threshold should not be compressed."""
        result = self.compressor.compress("read_file", "hello")
        assert result.content == "hello"
        assert result.savings_percent == 0.0

    def test_large_responses_compressed(self):
        """Responses above threshold should be compressed."""
        large_content = "\n".join(
            [f"line {i}: some content here" for i in range(100)]
        )
        result = self.compressor.compress("grep", large_content)
        assert result.compressed_tokens < result.original_tokens
        assert result.original_hash != ""

    def test_ccr_retrieval(self):
        """Compressed responses should be retrievable by hash."""
        content = "\n".join([f"line {i}" for i in range(50)])
        result = self.compressor.compress("read_file", content)
        if result.original_hash:
            retrieved = self.compressor.retrieve(result.original_hash)
            assert retrieved == content

    def test_retrieval_by_prefix(self):
        """Should be able to retrieve by hash prefix."""
        content = "\n".join([f"data {i}" for i in range(50)])
        result = self.compressor.compress("search", content)
        if result.original_hash:
            prefix = result.original_hash[:8]
            retrieved = self.compressor.retrieve(prefix)
            assert retrieved == content

    def test_stats_tracking(self):
        """Stats should track compressions."""
        content = "\n".join([f"line {i}" for i in range(30)])
        self.compressor.compress("tool1", content)
        self.compressor.compress("tool2", content)
        stats = self.compressor.stats
        assert stats["responses_compressed"] == 2
        assert stats["store_size"] >= 1


class TestSchemaCompressor:
    """Test suite for SchemaCompressor."""

    def setup_method(self):
        self.compressor = SchemaCompressor()

    def test_removes_descriptions(self):
        """Descriptions in schema properties should be removed."""
        schema = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The full path to the file to read",
                },
            },
        }
        result = self.compressor.compress(schema)
        props = result.compressed.get("properties", {})
        assert "description" not in props.get("path", {})

    def test_removes_examples(self):
        """Examples should be stripped from schemas."""
        schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "examples": ["hello", "world"],
                },
            },
        }
        result = self.compressor.compress(schema)
        props = result.compressed.get("properties", {})
        assert "examples" not in props.get("query", {})

    def test_preserves_type_info(self):
        """Type information should be preserved."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "name": {"type": "string"},
            },
            "required": ["count"],
        }
        result = self.compressor.compress(schema)
        assert result.compressed["properties"]["count"]["type"] == "integer"
        assert result.compressed["required"] == ["count"]

    def test_savings_reported(self):
        """Compression should report savings."""
        schema = {
            "type": "object",
            "description": "A complex schema with many verbose descriptions",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path to the file",
                    "examples": ["/home/user/file.txt"],
                },
                "encoding": {
                    "type": "string",
                    "description": "The character encoding to use",
                    "examples": ["utf-8", "ascii"],
                },
            },
        }
        result = self.compressor.compress(schema)
        assert result.savings_percent > 0
        assert result.compressed_size < result.original_size
