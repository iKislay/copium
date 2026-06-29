"""Tests for agent_context tool call classifier."""

from copium.agent_context.tool_call_classifier import (
    ClassifiedToolCall,
    ToolCallClassifier,
    ToolCallType,
    COMPRESSIBILITY,
    VALUE_SCORES,
)


class TestToolCallClassifier:
    """Test tool call classification."""

    def setup_method(self):
        self.classifier = ToolCallClassifier()

    def test_classify_list_dir(self):
        classified = self.classifier.classify("list_dir", {"path": "/src"})
        assert classified.tool_type == ToolCallType.DIRECTORY_LISTING
        assert classified.compressibility == 0.90
        assert classified.is_highly_compressible

    def test_classify_read_file(self):
        classified = self.classifier.classify("read_file", {"path": "main.py"})
        assert classified.tool_type == ToolCallType.FILE_READ
        assert classified.compressibility == 0.10
        assert not classified.is_highly_compressible
        assert classified.is_high_value

    def test_classify_grep(self):
        classified = self.classifier.classify("grep_search", {"query": "TODO"})
        assert classified.tool_type == ToolCallType.GREP_SEARCH
        assert classified.compressibility == 0.85

    def test_classify_write_file(self):
        classified = self.classifier.classify("write_file", {"path": "out.py"})
        assert classified.tool_type == ToolCallType.FILE_WRITE
        assert classified.is_high_value
        assert not classified.is_highly_compressible

    def test_classify_unknown_tool(self):
        classified = self.classifier.classify("custom_tool_xyz")
        assert classified.tool_type == ToolCallType.UNKNOWN

    def test_classify_command_with_test_hint(self):
        classified = self.classifier.classify(
            "run_command", {"command": "pytest tests/"}
        )
        assert classified.tool_type == ToolCallType.TEST_RUN

    def test_classify_command_with_git_hint(self):
        classified = self.classifier.classify(
            "run_command", {"command": "git status"}
        )
        assert classified.tool_type == ToolCallType.GIT_OPERATION

    def test_classify_config_file_by_extension(self):
        classified = self.classifier.classify(
            "custom_read", {"path": "config.yaml"}
        )
        assert classified.tool_type == ToolCallType.CONFIG_READ

    def test_classify_markdown_as_documentation(self):
        classified = self.classifier.classify(
            "custom_read", {"path": "README.md"}
        )
        assert classified.tool_type == ToolCallType.DOCUMENTATION

    def test_compression_priority(self):
        # High compressibility + low value = high priority
        dir_listing = self.classifier.classify("list_dir")
        # Low compressibility + high value = low priority
        file_read = self.classifier.classify("read_file", {"path": "x.py"})
        assert dir_listing.compression_priority > file_read.compression_priority

    def test_sort_by_compression_priority(self):
        classified = [
            self.classifier.classify("read_file", {"path": "x.py"}),
            self.classifier.classify("list_dir"),
            self.classifier.classify("grep_search"),
        ]
        sorted_calls = self.classifier.sort_by_compression_priority(classified)
        # Directory listing should come first (highest priority)
        assert sorted_calls[0].tool_type == ToolCallType.DIRECTORY_LISTING

    def test_classify_batch(self):
        batch = [
            {"name": "list_dir", "arguments": {"path": "/"}, "result_tokens": 100},
            {"name": "read_file", "arguments": {"path": "x.py"}, "result_tokens": 500},
        ]
        results = self.classifier.classify_batch(batch)
        assert len(results) == 2
        assert results[0].tool_type == ToolCallType.DIRECTORY_LISTING
        assert results[1].tool_type == ToolCallType.FILE_READ

    def test_custom_mappings(self):
        custom = {"my_special_tool": ToolCallType.ERROR_OUTPUT}
        classifier = ToolCallClassifier(custom_mappings=custom)
        classified = classifier.classify("my_special_tool")
        assert classified.tool_type == ToolCallType.ERROR_OUTPUT

    def test_package_json_higher_value(self):
        classified = self.classifier.classify(
            "read_file", {"path": "package.json"}
        )
        assert classified.value_score == 0.85

    def test_all_types_have_compressibility(self):
        for tool_type in ToolCallType:
            assert tool_type in COMPRESSIBILITY

    def test_all_types_have_value_scores(self):
        for tool_type in ToolCallType:
            assert tool_type in VALUE_SCORES
