"""Tests for progressive tool disclosure."""

from __future__ import annotations

import pytest

from copium.mcp_proxy.progressive_disclosure.config import ProgressiveDisclosureConfig
from copium.mcp_proxy.progressive_disclosure.registry import ToolSchemaRegistry
from copium.mcp_proxy.progressive_disclosure.eager_policy import EagerLoadingPolicy
from copium.mcp_proxy.progressive_disclosure.search import BM25Index
from copium.mcp_proxy.progressive_disclosure.engine import ProgressiveDisclosureEngine
from copium.mcp_proxy.progressive_disclosure.interceptor import (
    ProgressiveDisclosureInterceptor,
)
from copium.mcp_proxy.progressive_disclosure.meta_tools import (
    COPIUM_CALL_TOOL,
    COPIUM_FIND_TOOL,
    build_tool_list_summary,
)
from copium.mcp_proxy.progressive_disclosure.prompt_injection import (
    build_system_prompt_fragment,
)


# ─── Test Fixtures ─────────────────────────────────────────────────────

def _make_tool(name: str, description: str = "", params: dict | None = None) -> dict:
    """Create a mock tool definition."""
    return {
        "name": name,
        "description": description or f"Tool for {name}",
        "input_schema": {
            "type": "object",
            "properties": params or {"input": {"type": "string"}},
            "required": list((params or {"input": {}}).keys())[:1],
        },
    }


def _make_tools(count: int, prefix: str = "tool") -> list[dict]:
    """Create N mock tools."""
    tools = []
    for i in range(count):
        tools.append(_make_tool(
            f"{prefix}_{i}",
            f"This is {prefix} number {i} that performs actions.",
            {"arg1": {"type": "string"}, "arg2": {"type": "integer"}},
        ))
    return tools


SAMPLE_TOOLS = [
    _make_tool("github_create_issue", "Create a new issue in a GitHub repository"),
    _make_tool("github_list_prs", "List pull requests in a repository"),
    _make_tool("slack_send_message", "Send a message to a Slack channel"),
    _make_tool("jira_create_ticket", "Create a Jira ticket"),
    _make_tool("read_file", "Read contents of a file from the filesystem"),
    _make_tool("write_file", "Write contents to a file"),
    _make_tool("search_files", "Search for files matching a pattern"),
    _make_tool("grep_search", "Search file contents with regex"),
    _make_tool("run_command", "Execute a shell command"),
    _make_tool("postgres_query", "Run a SQL query against PostgreSQL"),
    _make_tool("datadog_get_metrics", "Fetch metrics from Datadog"),
    _make_tool("sentry_list_issues", "List issues from Sentry"),
]


# ─── Registry Tests ────────────────────────────────────────────────────

class TestToolSchemaRegistry:
    def test_register_and_lookup(self):
        reg = ToolSchemaRegistry()
        tool = _make_tool("my_tool", "Does things")
        tool_id = reg.register(tool)

        assert tool_id.startswith("tool_")
        entry = reg.get_by_name("my_tool")
        assert entry is not None
        assert entry.name == "my_tool"
        assert entry.description == "Does things"

    def test_case_insensitive_lookup(self):
        reg = ToolSchemaRegistry()
        reg.register(_make_tool("GitHub_CreateIssue", "Creates issues"))
        assert reg.get_by_name("github_createissue") is not None

    def test_all_entries(self):
        reg = ToolSchemaRegistry()
        for tool in SAMPLE_TOOLS:
            reg.register(tool)
        assert reg.tool_count == len(SAMPLE_TOOLS)
        assert len(reg.all_entries()) == len(SAMPLE_TOOLS)

    def test_record_call(self):
        reg = ToolSchemaRegistry()
        reg.register(_make_tool("my_tool"))
        reg.record_call("my_tool")
        entry = reg.get_by_name("my_tool")
        assert entry is not None
        assert entry.call_count == 1
        assert entry.last_called_at is not None

    def test_token_estimate(self):
        reg = ToolSchemaRegistry()
        reg.register(_make_tool("big_tool", "x" * 1000))
        assert reg.total_token_estimate > 0

    def test_clear(self):
        reg = ToolSchemaRegistry()
        reg.register(_make_tool("tool1"))
        reg.register(_make_tool("tool2"))
        reg.clear()
        assert reg.tool_count == 0

    def test_summary_generation(self):
        reg = ToolSchemaRegistry()
        reg.register(_make_tool("my_tool", "This is a very long description. It has multiple sentences."))
        entry = reg.get_by_name("my_tool")
        assert entry is not None
        assert entry.summary.startswith("my_tool:")
        assert "multiple sentences" not in entry.summary  # only first sentence


# ─── Eager Loading Policy Tests ────────────────────────────────────────

class TestEagerLoadingPolicy:
    def test_pattern_matching(self):
        config = ProgressiveDisclosureConfig(eager_patterns=["read_file", "search"])
        policy = EagerLoadingPolicy(config)

        reg = ToolSchemaRegistry()
        for tool in SAMPLE_TOOLS:
            reg.register(tool)

        eager, deferred = policy.classify(reg.all_entries())
        eager_names = {e.name for e in eager}

        assert "read_file" in eager_names
        assert "search_files" in eager_names
        assert "grep_search" in eager_names

    def test_prefix_matching(self):
        config = ProgressiveDisclosureConfig(eager_prefixes=["copium_"])
        policy = EagerLoadingPolicy(config)

        reg = ToolSchemaRegistry()
        reg.register(_make_tool("copium_find_tool"))
        reg.register(_make_tool("other_tool"))

        eager, deferred = policy.classify(reg.all_entries())
        eager_names = {e.name for e in eager}

        assert "copium_find_tool" in eager_names
        assert "other_tool" not in eager_names

    def test_call_count_makes_eager(self):
        config = ProgressiveDisclosureConfig(
            eager_patterns=[], eager_prefixes=[]
        )
        policy = EagerLoadingPolicy(config)

        reg = ToolSchemaRegistry()
        reg.register(_make_tool("rare_tool"))
        entry = reg.get_by_name("rare_tool")
        assert entry is not None
        entry.call_count = 1

        eager, deferred = policy.classify(reg.all_entries())
        assert any(e.name == "rare_tool" for e in eager)

    def test_respects_max_cap(self):
        config = ProgressiveDisclosureConfig(
            eager_load_max=3,
            eager_patterns=["tool"],
        )
        policy = EagerLoadingPolicy(config)

        reg = ToolSchemaRegistry()
        for tool in _make_tools(10):
            reg.register(tool)

        eager, deferred = policy.classify(reg.all_entries())
        assert len(eager) <= 3


# ─── BM25 Search Tests ─────────────────────────────────────────────────

class TestBM25Index:
    def test_basic_search(self):
        idx = BM25Index()
        idx.index_tool("github_create_issue", "Create a new issue in a GitHub repository")
        idx.index_tool("slack_send_message", "Send a message to a Slack channel")
        idx.index_tool("jira_create_ticket", "Create a ticket in Jira")

        results = idx.search("create github issue")
        assert len(results) > 0
        assert results[0].tool_name == "github_create_issue"

    def test_returns_top_k(self):
        idx = BM25Index()
        for tool in SAMPLE_TOOLS:
            idx.index_tool(tool["name"], tool["description"])

        results = idx.search("create something", top_k=2)
        assert len(results) <= 2

    def test_no_results_for_irrelevant_query(self):
        idx = BM25Index()
        idx.index_tool("github_create_issue", "Create a GitHub issue")
        results = idx.search("quantum physics simulation")
        # May still return results due to partial matches, but scores should be low
        if results:
            assert results[0].score < 2.0

    def test_parameter_indexing(self):
        idx = BM25Index()
        idx.index_tool(
            "postgres_query",
            "Run SQL",
            {"properties": {"database": {}, "query_text": {}}},
        )
        results = idx.search("database query")
        assert len(results) > 0
        assert results[0].tool_name == "postgres_query"

    def test_empty_index(self):
        idx = BM25Index()
        results = idx.search("anything")
        assert results == []

    def test_clear(self):
        idx = BM25Index()
        idx.index_tool("tool1", "description")
        idx.clear()
        assert idx.search("tool1") == []


# ─── Engine Tests ──────────────────────────────────────────────────────

class TestProgressiveDisclosureEngine:
    def test_below_threshold_passthrough(self):
        config = ProgressiveDisclosureConfig(min_tools_for_disclosure=20)
        engine = ProgressiveDisclosureEngine(config)
        engine.register_tools(SAMPLE_TOOLS)
        result = engine.process()

        assert result.deferred_count == 0
        assert len(result.tools_for_llm) == len(SAMPLE_TOOLS)
        assert result.system_prompt_fragment == ""

    def test_above_threshold_applies_disclosure(self):
        config = ProgressiveDisclosureConfig(
            min_tools_for_disclosure=5,
            eager_load_max=5,
        )
        engine = ProgressiveDisclosureEngine(config)
        engine.register_tools(SAMPLE_TOOLS)
        result = engine.process()

        assert result.deferred_count > 0
        assert result.eager_count <= 5
        # Should include meta-tools
        tool_names = {t["name"] for t in result.tools_for_llm}
        assert "copium_find_tool" in tool_names
        assert "copium_call_tool" in tool_names
        assert result.savings_pct > 0

    def test_handle_find_tool(self):
        config = ProgressiveDisclosureConfig(min_tools_for_disclosure=5)
        engine = ProgressiveDisclosureEngine(config)
        engine.register_tools(SAMPLE_TOOLS)

        result = engine.handle_find_tool({"query": "create github issue"})
        assert len(result.tools) > 0
        assert any(t["name"] == "github_create_issue" for t in result.tools)

    def test_handle_call_tool_success(self):
        engine = ProgressiveDisclosureEngine()
        engine.register_tools(SAMPLE_TOOLS)

        result = engine.handle_call_tool({
            "tool_name": "github_create_issue",
            "arguments": {"title": "Bug"},
        })
        assert result.error is None
        assert result.tool_name == "github_create_issue"
        assert result.arguments == {"title": "Bug"}

    def test_handle_call_tool_not_found(self):
        engine = ProgressiveDisclosureEngine()
        engine.register_tools(SAMPLE_TOOLS)

        result = engine.handle_call_tool({
            "tool_name": "nonexistent_tool",
            "arguments": {},
        })
        assert result.error is not None
        assert "not found" in result.error

    def test_format_find_tool_response(self):
        engine = ProgressiveDisclosureEngine()
        engine.register_tools(SAMPLE_TOOLS)

        find_result = engine.handle_find_tool({"query": "github"})
        response = engine.format_find_tool_response(find_result)
        assert "copium_call_tool" in response

    def test_openai_format_tools(self):
        """Test that OpenAI function-call format tools are handled."""
        config = ProgressiveDisclosureConfig(min_tools_for_disclosure=3)
        engine = ProgressiveDisclosureEngine(config)

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search the web",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            },
        ]
        engine.register_tools(openai_tools)
        assert engine.registry.tool_count == 3


# ─── Interceptor Tests ─────────────────────────────────────────────────

class TestProgressiveDisclosureInterceptor:
    def test_disabled_passthrough(self):
        config = ProgressiveDisclosureConfig(enabled=False)
        interceptor = ProgressiveDisclosureInterceptor(config)
        body = {"tools": SAMPLE_TOOLS, "messages": []}
        result = interceptor.intercept_request(body)
        assert result["tools"] == SAMPLE_TOOLS

    def test_no_tools_passthrough(self):
        interceptor = ProgressiveDisclosureInterceptor()
        body = {"messages": [{"role": "user", "content": "hello"}]}
        result = interceptor.intercept_request(body)
        assert "tools" not in result

    def test_applies_disclosure(self):
        config = ProgressiveDisclosureConfig(
            min_tools_for_disclosure=5,
            eager_load_max=4,
        )
        interceptor = ProgressiveDisclosureInterceptor(config)
        body = {"tools": SAMPLE_TOOLS, "messages": [], "system": "You are helpful."}
        result = interceptor.intercept_request(body)

        # Should have fewer tools than original
        assert len(result["tools"]) < len(SAMPLE_TOOLS)
        # Should include meta-tools
        tool_names = {t["name"] for t in result["tools"]}
        assert "copium_find_tool" in tool_names
        assert "copium_call_tool" in tool_names

    def test_system_prompt_injection_anthropic(self):
        config = ProgressiveDisclosureConfig(
            min_tools_for_disclosure=5,
            inject_system_prompt=True,
        )
        interceptor = ProgressiveDisclosureInterceptor(config)
        body = {"tools": SAMPLE_TOOLS, "messages": [], "system": "Base prompt."}
        result = interceptor.intercept_request(body)
        assert "Tool Discovery" in result["system"]

    def test_system_prompt_injection_openai(self):
        config = ProgressiveDisclosureConfig(
            min_tools_for_disclosure=5,
            inject_system_prompt=True,
        )
        interceptor = ProgressiveDisclosureInterceptor(config)
        body = {
            "tools": SAMPLE_TOOLS,
            "messages": [{"role": "system", "content": "Base prompt."}],
        }
        result = interceptor.intercept_request(body)
        assert "Tool Discovery" in result["messages"][0]["content"]

    def test_intercept_find_tool_call(self):
        config = ProgressiveDisclosureConfig(min_tools_for_disclosure=5)
        interceptor = ProgressiveDisclosureInterceptor(config)
        interceptor.intercept_request({"tools": SAMPLE_TOOLS, "messages": []})

        response = interceptor.intercept_tool_call(
            "copium_find_tool", {"query": "github"}
        )
        assert response is not None
        assert response["type"] == "text"
        assert "github" in response["text"].lower()

    def test_intercept_call_tool(self):
        config = ProgressiveDisclosureConfig(min_tools_for_disclosure=5)
        interceptor = ProgressiveDisclosureInterceptor(config)
        interceptor.intercept_request({"tools": SAMPLE_TOOLS, "messages": []})

        response = interceptor.intercept_tool_call(
            "copium_call_tool",
            {"tool_name": "github_create_issue", "arguments": {"title": "Test"}},
        )
        assert response is not None
        assert response["type"] == "dispatch"
        assert response["tool_name"] == "github_create_issue"

    def test_non_meta_tool_returns_none(self):
        interceptor = ProgressiveDisclosureInterceptor()
        response = interceptor.intercept_tool_call("some_other_tool", {})
        assert response is None

    def test_get_metrics(self):
        config = ProgressiveDisclosureConfig(min_tools_for_disclosure=5)
        interceptor = ProgressiveDisclosureInterceptor(config)

        # Before any request
        metrics = interceptor.get_metrics()
        assert metrics["active"] is False

        # After a request
        interceptor.intercept_request({"tools": SAMPLE_TOOLS, "messages": []})
        metrics = interceptor.get_metrics()
        assert metrics["active"] is True
        assert metrics["total_tools"] == len(SAMPLE_TOOLS)
        assert metrics["savings_pct"] > 0


# ─── Meta-Tools Tests ──────────────────────────────────────────────────

class TestMetaTools:
    def test_find_tool_schema_valid(self):
        assert COPIUM_FIND_TOOL["name"] == "copium_find_tool"
        assert "query" in COPIUM_FIND_TOOL["input_schema"]["required"]

    def test_call_tool_schema_valid(self):
        assert COPIUM_CALL_TOOL["name"] == "copium_call_tool"
        assert "tool_name" in COPIUM_CALL_TOOL["input_schema"]["required"]
        assert "arguments" in COPIUM_CALL_TOOL["input_schema"]["required"]

    def test_build_tool_list_summary(self):
        reg = ToolSchemaRegistry()
        for tool in SAMPLE_TOOLS[:3]:
            reg.register(tool)

        summary = build_tool_list_summary(reg.all_entries(), deferred_count=9)
        assert "3 loaded" in summary
        assert "9 discoverable" in summary


# ─── Prompt Injection Tests ────────────────────────────────────────────

class TestPromptInjection:
    def test_fragment_content(self):
        reg = ToolSchemaRegistry()
        for tool in SAMPLE_TOOLS[:3]:
            reg.register(tool)

        fragment = build_system_prompt_fragment(
            eager_tools=reg.all_entries(),
            deferred_count=9,
            total_tools=12,
        )
        assert "12 tools total" in fragment
        assert "3 are loaded" in fragment
        assert "9 additional" in fragment
        assert "copium_find_tool" in fragment


# ─── Integration Tests ─────────────────────────────────────────────────

class TestEndToEnd:
    """End-to-end integration tests simulating full proxy flow."""

    def test_full_flow_anthropic(self):
        """Simulate: client sends 12 tools, proxy discloses, LLM finds and calls."""
        config = ProgressiveDisclosureConfig(
            min_tools_for_disclosure=5,
            eager_load_max=4,
        )
        interceptor = ProgressiveDisclosureInterceptor(config)

        # Step 1: Client sends request with 12 tools
        request = {
            "model": "claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "Create a GitHub issue"}],
            "system": "You are a helpful assistant.",
            "tools": SAMPLE_TOOLS,
        }
        modified = interceptor.intercept_request(request)

        # Verify: fewer tools, meta-tools present
        assert len(modified["tools"]) < 12
        tool_names = {t["name"] for t in modified["tools"]}
        assert "copium_find_tool" in tool_names

        # Step 2: LLM calls copium_find_tool
        find_response = interceptor.intercept_tool_call(
            "copium_find_tool", {"query": "create github issue"}
        )
        assert find_response is not None
        assert "github_create_issue" in find_response["text"]

        # Step 3: LLM calls copium_call_tool
        call_response = interceptor.intercept_tool_call(
            "copium_call_tool",
            {"tool_name": "github_create_issue", "arguments": {"title": "Bug report"}},
        )
        assert call_response is not None
        assert call_response["type"] == "dispatch"
        assert call_response["tool_name"] == "github_create_issue"

    def test_token_savings_calculation(self):
        """Verify that reported savings are reasonable."""
        config = ProgressiveDisclosureConfig(
            min_tools_for_disclosure=5,
            eager_load_max=3,
        )
        interceptor = ProgressiveDisclosureInterceptor(config)

        # Use many tools to maximize savings
        tools = _make_tools(30)
        interceptor.intercept_request({"tools": tools, "messages": []})

        metrics = interceptor.get_metrics()
        assert metrics["savings_pct"] > 50  # Should save at least 50%
        assert metrics["deferred_count"] > 20  # Most tools deferred
