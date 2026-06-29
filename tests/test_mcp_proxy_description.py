"""Tests for the MCP proxy description compressor."""

from __future__ import annotations

from copium.mcp_proxy.description_compressor import DescriptionCompressor


class TestDescriptionCompressor:
    """Test suite for DescriptionCompressor."""

    def setup_method(self):
        self.compressor = DescriptionCompressor()

    def test_strips_verbose_preamble(self):
        """Verbose 'This tool allows you to...' should be stripped."""
        tool = {
            "name": "read_file",
            "description": (
                "This tool allows you to read a file from the local filesystem. "
                "It supports both absolute and relative paths."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = self.compressor.compress(tool)
        assert "This tool allows you to" not in result.description
        assert result.compressed_tokens < result.original_tokens

    def test_strips_filler_words(self):
        """Filler words like 'basically', 'simply' should be removed."""
        tool = {
            "name": "search",
            "description": "This basically searches the codebase simply by pattern.",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = self.compressor.compress(tool)
        assert "basically" not in result.description
        assert "simply" not in result.description

    def test_preserves_short_descriptions(self):
        """Short descriptions should pass through mostly unchanged."""
        tool = {
            "name": "ping",
            "description": "Check server connectivity.",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = self.compressor.compress(tool)
        # Should not be empty
        assert len(result.description) > 0

    def test_removes_code_examples(self):
        """Code blocks in descriptions should be stripped."""
        tool = {
            "name": "execute",
            "description": (
                "Execute a command.\n\n"
                "```python\nresult = execute('ls')\n```\n\n"
                "Returns the output."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = self.compressor.compress(tool)
        assert "```" not in result.description

    def test_compresses_parameter_descriptions(self):
        """Verbose param descriptions should be shortened."""
        tool = {
            "name": "read_file",
            "description": "Read a file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "The absolute or relative path to the file that you "
                            "want to read from the local filesystem. Must be a valid "
                            "path that exists on the system."
                        ),
                    },
                },
                "required": ["path"],
            },
        }
        result = self.compressor.compress(tool)
        param_desc = result.input_schema["properties"]["path"]["description"]
        # Should be shorter than original
        assert len(param_desc) < 150

    def test_savings_calculation(self):
        """savings_percent should be reasonable for verbose input."""
        tool = {
            "name": "complex_tool",
            "description": (
                "This tool allows you to perform complex operations on the "
                "filesystem. Use this tool when you need to manipulate files "
                "and directories. For example, you can create, read, update, "
                "and delete files. Note that this tool requires proper permissions."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = self.compressor.compress(tool)
        assert result.savings_percent > 30

    def test_stats_accumulate(self):
        """Stats should accumulate across multiple compressions."""
        tools = [
            {
                "name": f"tool_{i}",
                "description": f"This tool allows you to do thing {i} with data.",
                "inputSchema": {"type": "object", "properties": {}},
            }
            for i in range(5)
        ]
        for tool in tools:
            self.compressor.compress(tool)

        assert self.compressor.stats["tools_compressed"] == 5
        assert self.compressor.stats["savings_percent"] > 0

    def test_handles_empty_description(self):
        """Empty descriptions should not crash."""
        tool = {
            "name": "no_desc",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = self.compressor.compress(tool)
        assert result.description == ""

    def test_realistic_mcp_tool(self):
        """Test with a realistic MCP tool definition (filesystem read)."""
        tool = {
            "name": "read_file",
            "description": (
                "Read the complete contents of a file from the file system. "
                "Handles various text encodings and provides detailed error "
                "messages if the file cannot be read. Use this tool when you "
                "need to examine the contents of a single file. Only works "
                "within allowed directories."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Full path to the file to read",
                    }
                },
                "required": ["path"],
            },
        }
        result = self.compressor.compress(tool)
        assert result.compressed_tokens < result.original_tokens
        assert len(result.description) > 0
        assert result.name == "read_file"
