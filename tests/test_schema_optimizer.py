"""Tests for the TF-IDF schema optimizer."""

from __future__ import annotations

import pytest

from copium.transforms.schema_optimizer import (
    SchemaOptimizerConfig,
    TFIDFSchemaOptimizer,
    _build_tfidf,
    _tool_name,
    _tool_to_text,
    _tokenize,
)


def _make_openai_tool(name: str, description: str, params: dict | None = None) -> dict:
    """Create a minimal OpenAI-format tool definition."""
    tool = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": params or {},
                "required": [],
            },
        },
    }
    return tool


def _make_anthropic_tool(name: str, description: str, props: dict | None = None) -> dict:
    """Create a minimal Anthropic-format tool definition."""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": props or {},
        },
    }


class TestTokenize:
    """Tests for the tokenizer."""

    def test_basic_words(self) -> None:
        """Splits simple words correctly."""
        assert _tokenize("read file") == ["read", "file"]

    def test_snake_case(self) -> None:
        """Splits snake_case into parts."""
        result = _tokenize("read_file")
        assert "read" in result
        assert "file" in result

    def test_empty_string(self) -> None:
        """Empty string returns empty list."""
        assert _tokenize("") == []

    def test_none_like_empty(self) -> None:
        """Tokenizes empty string correctly."""
        assert _tokenize("") == []

    def test_single_chars_dropped(self) -> None:
        """Single characters are dropped."""
        result = _tokenize("a b c word")
        assert "a" not in result
        assert "word" in result


class TestToolToText:
    """Tests for _tool_to_text serialization."""

    def test_openai_format(self) -> None:
        """Extracts text from OpenAI-format tool."""
        tool = _make_openai_tool("read_file", "Read a file from the filesystem")
        config = SchemaOptimizerConfig()
        text = _tool_to_text(tool, config)
        assert "read_file" in text
        assert "Read" in text

    def test_anthropic_format(self) -> None:
        """Extracts text from Anthropic-format tool."""
        tool = _make_anthropic_tool("write_file", "Write content to a file")
        config = SchemaOptimizerConfig()
        text = _tool_to_text(tool, config)
        assert "write_file" in text
        assert "Write" in text

    def test_includes_params(self) -> None:
        """Includes parameter names when enabled."""
        tool = _make_openai_tool(
            "search_code",
            "Search codebase",
            params={"query": {"type": "string", "description": "search query"}},
        )
        config = SchemaOptimizerConfig(include_param_names=True)
        text = _tool_to_text(tool, config)
        assert "query" in text


class TestToolName:
    """Tests for _tool_name extraction."""

    def test_openai_name(self) -> None:
        """Extracts name from OpenAI-format tool."""
        tool = _make_openai_tool("my_tool", "desc")
        assert _tool_name(tool) == "my_tool"

    def test_anthropic_name(self) -> None:
        """Extracts name from Anthropic-format tool."""
        tool = _make_anthropic_tool("another_tool", "desc")
        assert _tool_name(tool) == "another_tool"

    def test_unnamed_tool(self) -> None:
        """Returns sentinel for tool without a name."""
        assert _tool_name({}) == "(unnamed)"


class TestBuildTFIDF:
    """Tests for the TF-IDF scoring engine."""

    def test_matching_doc_scores_higher(self) -> None:
        """A document that matches the query scores higher than one that doesn't."""
        docs = [
            _tokenize("read file filesystem path content"),
            _tokenize("execute sql database query records"),
        ]
        query = _tokenize("read file")
        scores = _build_tfidf(docs, query)
        assert scores[0] > scores[1]

    def test_no_match_scores_zero(self) -> None:
        """A document with no query terms scores 0."""
        docs = [_tokenize("alpha beta gamma")]
        query = _tokenize("completely different words")
        scores = _build_tfidf(docs, query)
        assert scores[0] == 0.0

    def test_empty_query_returns_zeros(self) -> None:
        """Empty query returns all zeros."""
        docs = [_tokenize("some content"), _tokenize("other content")]
        scores = _build_tfidf(docs, [])
        assert all(s == 0.0 for s in scores)

    def test_returns_one_score_per_doc(self) -> None:
        """Returns exactly one score per document."""
        docs = [_tokenize("a b c"), _tokenize("d e f"), _tokenize("g h i")]
        scores = _build_tfidf(docs, _tokenize("a b"))
        assert len(scores) == 3


class TestTFIDFSchemaOptimizer:
    """Integration tests for TFIDFSchemaOptimizer."""

    def _make_tool_set(self) -> list[dict]:
        """Create a diverse set of 15 tools."""
        tools = [
            _make_openai_tool("read_file", "Read file content from disk", {"path": {"type": "string"}}),
            _make_openai_tool("write_file", "Write content to a file", {"path": {"type": "string"}, "content": {"type": "string"}}),
            _make_openai_tool("search_code", "Search for patterns in code"),
            _make_openai_tool("run_tests", "Execute test suite"),
            _make_openai_tool("git_diff", "Show git diff for changes"),
            _make_openai_tool("git_commit", "Commit staged changes"),
            _make_openai_tool("sql_query", "Run SQL query on database"),
            _make_openai_tool("send_email", "Send an email message"),
            _make_openai_tool("create_ticket", "Create issue in tracker"),
            _make_openai_tool("deploy_app", "Deploy application to cloud"),
            _make_openai_tool("get_weather", "Fetch current weather data"),
            _make_openai_tool("translate_text", "Translate text to another language"),
            _make_openai_tool("resize_image", "Resize and crop image files"),
        ]
        return tools

    def test_prune_reduces_tool_count(self) -> None:
        """Optimizer reduces tool count when above threshold."""
        tools = self._make_tool_set()
        config = SchemaOptimizerConfig(enabled=True, max_tools=5, min_tools_to_optimize=10)
        optimizer = TFIDFSchemaOptimizer(config)
        pruned, kept, total = optimizer.prune(tools, "read file from disk")
        assert total == len(tools)
        assert kept <= 5

    def test_prune_keeps_relevant_tools(self) -> None:
        """File-related context keeps file tools in top results."""
        tools = self._make_tool_set()
        config = SchemaOptimizerConfig(enabled=True, max_tools=5, min_tools_to_optimize=10)
        optimizer = TFIDFSchemaOptimizer(config)
        pruned, kept, total = optimizer.prune(tools, "I need to read a file from disk")
        pruned_names = {_tool_name(t) for t in pruned}
        assert "read_file" in pruned_names, f"Expected read_file in {pruned_names}"

    def test_prune_disabled_returns_original(self) -> None:
        """Disabled optimizer returns all tools unchanged."""
        tools = self._make_tool_set()
        config = SchemaOptimizerConfig(enabled=False)
        optimizer = TFIDFSchemaOptimizer(config)
        pruned, kept, total = optimizer.prune(tools, "read file")
        assert len(pruned) == len(tools)
        assert kept == total

    def test_prune_skips_small_tool_sets(self) -> None:
        """Optimizer is a no-op when fewer tools than threshold."""
        tools = self._make_tool_set()[:5]
        config = SchemaOptimizerConfig(enabled=True, min_tools_to_optimize=10)
        optimizer = TFIDFSchemaOptimizer(config)
        pruned, kept, total = optimizer.prune(tools, "read file")
        assert len(pruned) == len(tools)

    def test_always_keep_pinned(self) -> None:
        """always_keep tools are always included regardless of relevance."""
        tools = self._make_tool_set()
        config = SchemaOptimizerConfig(
            enabled=True,
            max_tools=3,
            min_tools_to_optimize=10,
            always_keep=["get_weather"],  # Irrelevant but pinned
        )
        optimizer = TFIDFSchemaOptimizer(config)
        pruned, _, _ = optimizer.prune(tools, "read file from disk")
        pruned_names = {_tool_name(t) for t in pruned}
        assert "get_weather" in pruned_names

    def test_score_tools_returns_ranked_list(self) -> None:
        """score_tools returns tools sorted by relevance."""
        tools = self._make_tool_set()
        config = SchemaOptimizerConfig()
        optimizer = TFIDFSchemaOptimizer(config)
        scored = optimizer.score_tools(tools, "run sql query database")
        assert len(scored) == len(tools)
        # sql_query should be ranked high for this context
        names_in_order = [name for name, _ in scored]
        sql_pos = names_in_order.index("sql_query")
        assert sql_pos < len(tools) // 2, f"sql_query ranked too low: pos={sql_pos}"

    def test_anthropic_format_tools(self) -> None:
        """Optimizer works with Anthropic-format tools."""
        tools = [
            _make_anthropic_tool("read_file", "Read file content"),
            _make_anthropic_tool("send_email", "Send email to recipient"),
            _make_anthropic_tool("run_query", "Execute database query"),
            _make_anthropic_tool("deploy", "Deploy application"),
            _make_anthropic_tool("resize_image", "Resize image"),
            _make_anthropic_tool("fetch_weather", "Get weather data"),
            _make_anthropic_tool("translate", "Translate text language"),
            _make_anthropic_tool("git_commit", "Commit code changes"),
            _make_anthropic_tool("write_file", "Write to file"),
            _make_anthropic_tool("search_docs", "Search documentation"),
            _make_anthropic_tool("create_ticket", "Create support ticket"),
            _make_anthropic_tool("check_status", "Check service status"),
        ]
        config = SchemaOptimizerConfig(enabled=True, max_tools=5, min_tools_to_optimize=10)
        optimizer = TFIDFSchemaOptimizer(config)
        pruned, kept, total = optimizer.prune(tools, "read file from disk")
        assert kept <= 5
        pruned_names = {_tool_name(t) for t in pruned}
        assert "read_file" in pruned_names
