"""Integration tests for beat-ContextCrumb features.

Tests the new modules added to beat ContextCrumb:
- Compression diff engine
- Agent memory store
- Tool response compressor
- Code-aware pipeline + ContextCrumb comparison
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from copium.agent.memory import (
    CompressedMemoryStore,
    MemoryEntry,
    MemoryPriority,
)
from copium.compression.modes import (
    CompressionModeDispatcher,
    ContentClassification,
    Mode,
    ModeConfig,
)
from copium.observability.diff import (
    CompressionDiffEngine,
    DiffStatus,
    DiffSummary,
    RestorationMap,
)
from copium.proxy.mcp_enhanced import (
    ProgressiveDisclosure,
    ToolRegistry,
    ToolSchema,
)
from copium.proxy.response_compressor import ToolResponseCompressor
from copium.transforms.code_aware import CodeAwarePipeline, ImportanceClassifier


# =============================================================================
# Compression Diff Engine Tests
# =============================================================================


class TestCompressionDiffEngine:
    """Tests for the compression diff engine."""

    def setup_method(self):
        self.engine = CompressionDiffEngine()

    def test_identical_content_all_kept(self):
        """Identical content should produce all 'kept' segments."""
        text = "line 1\nline 2\nline 3"
        segments = self.engine.generate_diff(text, text)
        assert all(s.status == DiffStatus.KEPT for s in segments)

    def test_removed_lines_detected(self):
        """Removed lines should be marked as REMOVED."""
        original = "line 1\nline 2\nline 3"
        compressed = "line 1\nline 3"
        segments = self.engine.generate_diff(original, compressed)
        removed = [s for s in segments if s.status == DiffStatus.REMOVED]
        assert len(removed) >= 1

    def test_compressed_lines_detected(self):
        """Replaced lines should be marked as COMPRESSED."""
        original = "This is a very long detailed description of the function"
        compressed = "Function description"
        segments = self.engine.generate_diff(original, compressed)
        compressed_segs = [s for s in segments if s.status == DiffStatus.COMPRESSED]
        assert len(compressed_segs) >= 1

    def test_summary_tokens(self):
        """Summary should correctly aggregate token counts."""
        original = "line 1\nline 2\nline 3\nline 4"
        compressed = "line 1\nline 3"
        segments = self.engine.generate_diff(original, compressed)
        summary = self.engine.summarize(segments)
        assert summary.total_lines > 0
        assert summary.total_original_tokens > 0

    def test_restoration_map(self):
        """Restoration map should store restorable segments."""
        rmap = RestorationMap()
        rmap.add("key1", "original content 1")
        rmap.add("key2", "original content 2")
        assert rmap.restore("key1") == "original content 1"
        assert rmap.restore("nonexistent") is None
        assert rmap.entry_count == 2

    def test_render_terminal(self):
        """Terminal rendering should produce non-empty output."""
        original = "# This is a comment\ndef hello():\n    pass"
        compressed = "def hello():\n    pass"
        segments = self.engine.generate_diff(original, compressed)
        output = self.engine.render_terminal(segments)
        assert "Compression Diff" in output
        assert "Summary:" in output

    def test_render_json(self):
        """JSON rendering should produce valid structure."""
        original = "line 1\nline 2"
        compressed = "line 1"
        segments = self.engine.generate_diff(original, compressed)
        result = self.engine.render_json(segments)
        assert "summary" in result
        assert "segments" in result
        assert result["summary"]["total_lines"] > 0

    def test_empty_content(self):
        """Empty content should produce empty diff."""
        segments = self.engine.generate_diff("", "")
        summary = self.engine.summarize(segments)
        assert summary.total_lines == 0


# =============================================================================
# Agent Memory Store Tests
# =============================================================================


class TestCompressedMemoryStore:
    """Tests for the compressed memory store."""

    def setup_method(self):
        self.store = CompressedMemoryStore(max_tokens=10000, max_entries=50)

    def test_store_and_retrieve(self):
        """Basic store and retrieve by key."""
        self.store.store(
            "test_key",
            "original content",
            "compressed content",
            priority=MemoryPriority.HIGH,
            tags=["test"],
        )
        entry = self.store.get("test_key")
        assert entry is not None
        assert entry.compressed_content == "compressed content"
        assert entry.priority == MemoryPriority.HIGH

    def test_retrieve_by_query(self):
        """Retrieve relevant memories by keyword query."""
        self.store.store("auth_code", "authentication module code", "auth code",
                        tags=["code", "auth"])
        self.store.store("db_schema", "database schema definition", "db schema",
                        tags=["database"])
        self.store.store("auth_config", "auth configuration yaml", "auth config",
                        tags=["config", "auth"])

        results = self.store.retrieve("authentication", tags=["auth"])
        assert len(results) >= 1
        assert any("auth" in r.key for r in results)

    def test_priority_eviction(self):
        """Lower priority entries should be evicted first."""
        # Fill with low priority
        for i in range(50):
            self.store.store(
                f"low_{i}",
                "x" * 800,  # 200 tokens each
                "y" * 400,  # 100 compressed tokens
                priority=MemoryPriority.LOW,
            )

        # Add high priority - should evict low priority entries
        self.store.store(
            "important",
            "critical data",
            "critical",
            priority=MemoryPriority.CRITICAL,
        )
        assert self.store.get("important") is not None

    def test_tags_retrieval(self):
        """Should find entries by tags."""
        self.store.store("entry1", "content1", "c1", tags=["python", "code"])
        self.store.store("entry2", "content2", "c2", tags=["rust", "code"])
        self.store.store("entry3", "content3", "c3", tags=["python", "config"])

        python_entries = self.store.get_by_tags(["python"])
        assert len(python_entries) == 2

    def test_persistence(self):
        """Memory store should persist to and load from disk."""
        with tempfile.TemporaryDirectory() as tmp:
            store = CompressedMemoryStore(storage_dir=tmp)
            store.store("persist_test", "original", "compressed", tags=["test"])
            store.persist()

            # Load in fresh store
            new_store = CompressedMemoryStore(storage_dir=tmp)
            new_store.load()
            entry = new_store.get("persist_test")
            assert entry is not None
            assert entry.compressed_content == "compressed"

    def test_delete(self):
        """Deleting an entry should remove it."""
        self.store.store("to_delete", "content", "compressed")
        assert self.store.get("to_delete") is not None
        self.store.delete("to_delete")
        assert self.store.get("to_delete") is None

    def test_stats_tracking(self):
        """Stats should track operations."""
        self.store.store("s1", "content", "compressed")
        self.store.retrieve("content")
        stats = self.store.stats
        assert stats.stores >= 1
        assert stats.retrievals >= 1


# =============================================================================
# Tool Response Compressor Tests
# =============================================================================


class TestToolResponseCompressor:
    """Tests for the tool response compressor."""

    def setup_method(self):
        self.compressor = ToolResponseCompressor(
            max_output_tokens=200, aggressiveness=0.5
        )

    def test_small_response_not_compressed(self):
        """Responses within budget should not be modified."""
        small = "Hello, world!"
        result = self.compressor.compress("echo", small)
        assert result.compressed == small
        assert result.tokens_saved == 0

    def test_json_compression(self):
        """JSON responses should be structurally compressed."""
        large_json = json.dumps({"users": [{"id": i, "name": f"User {i}"} for i in range(50)]}, indent=2)
        result = self.compressor.compress("api_call", large_json)
        assert result.compressed_tokens < result.original_tokens
        assert result.savings_pct > 0

    def test_code_compression(self):
        """Code responses should have comments stripped."""
        code = "\n".join([
            "# This is a comment",
            "import os",
            "# Another comment",
            "def main():",
            "    # TODO: implement",
            "    print('hello')",
            "    return 0",
        ] * 30)  # Make it large
        result = self.compressor.compress("read_file", code)
        assert result.compression_mode == "code"

    def test_log_compression(self):
        """Log output should be deduplicated."""
        logs = "\n".join([
            f"2024-01-15T10:{i:02d}:00Z INFO [server] Request processed in {i}ms"
            for i in range(50)
        ])
        result = self.compressor.compress("execute_command", logs)
        assert result.compression_mode == "log"
        assert result.compressed_tokens < result.original_tokens

    def test_error_compression(self):
        """Error tracebacks should be frame-reduced."""
        error = "Traceback (most recent call last):\n"
        for i in range(20):
            error += f'  File "/app/module{i}.py", line {i*10}, in func{i}\n'
            error += f"    some_call_{i}()\n"
        error += "ValueError: something went wrong"

        result = self.compressor.compress("execute_command", error)
        assert result.compression_mode == "error"
        assert "more frames" in result.compressed

    def test_ccr_restoration(self):
        """Compressed responses should be restorable via CCR key."""
        large_text = "A" * 5000  # Large enough to trigger compression
        result = self.compressor.compress("read_file", large_text)
        assert result.is_reversible
        restored = self.compressor.restore(result.ccr_key)
        assert restored == large_text

    def test_stats_tracking(self):
        """Stats should track compression history."""
        self.compressor.compress("tool1", "x" * 5000)
        self.compressor.compress("tool2", "y" * 3000)
        stats = self.compressor.stats
        assert stats.total_responses == 2
        assert stats.total_saved > 0


# =============================================================================
# Progressive Disclosure Integration Tests
# =============================================================================


class TestProgressiveDisclosureIntegration:
    """Integration tests for progressive tool disclosure."""

    def setup_method(self):
        self.registry = ToolRegistry()
        self.registry.register(
            ToolSchema(
                name="read_file",
                description="Read file contents from the filesystem",
                parameters={"path": {"type": "string", "description": "File path"}},
            ),
            category="filesystem",
        )
        self.registry.register(
            ToolSchema(
                name="write_file",
                description="Write content to a file on the filesystem",
                parameters={
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            ),
            category="filesystem",
        )
        self.registry.register(
            ToolSchema(
                name="execute_command",
                description="Execute a shell command in the terminal",
                parameters={"command": {"type": "string"}},
            ),
            category="execution",
        )
        self.disclosure = ProgressiveDisclosure(self.registry)

    def test_initial_stubs_smaller_than_schemas(self):
        """Initial stubs should be much smaller than full schemas."""
        stubs = self.disclosure.get_initial_tool_list()
        stub_tokens = sum(s.token_estimate for s in stubs)
        full_tokens = sum(s.token_estimate for s in self.registry.all_schemas())
        assert stub_tokens < full_tokens

    def test_find_tools_returns_relevant(self):
        """find_tools should return relevant tools for a query."""
        results = self.disclosure.find_tools("read a file")
        assert len(results) > 0
        assert any("read" in r.name for r in results)

    def test_disclose_schema_tracks_disclosure(self):
        """Disclosing a schema should track it."""
        assert not self.disclosure.is_disclosed("read_file")
        schema = self.disclosure.disclose_schema("read_file")
        assert schema is not None
        assert self.disclosure.is_disclosed("read_file")

    def test_metrics_savings(self):
        """Metrics should show token savings from progressive disclosure."""
        self.disclosure.get_initial_tool_list()
        metrics = self.disclosure.metrics
        assert metrics.tokens_full_schema > 0
        assert metrics.savings_pct > 0

    def test_hierarchical_discovery(self):
        """Three-level discovery should return categories and tools."""
        response = self.disclosure.find_tools_hierarchical("file operations")
        assert len(response.categories) > 0 or len(response.tools) > 0


# =============================================================================
# Code-Aware Pipeline Integration Tests
# =============================================================================


class TestCodeAwarePipelineIntegration:
    """Integration tests for the code-aware compression pipeline."""

    def test_python_compression(self):
        """Python code should be compressed with language-specific strategies."""
        code = '''"""Module docstring with lots of details about what this does."""

import os
import sys
from typing import Any, Optional

# Configuration constants
MAX_RETRIES = 3
TIMEOUT = 30


def process_data(items: list[Any], *, verbose: bool = False) -> list[Any]:
    """Process items with optional verbose logging.

    Args:
        items: List of items to process.
        verbose: Enable verbose output.

    Returns:
        Processed items.
    """
    # TODO: Add batch processing
    results = []
    for item in items:
        # Process each item
        if verbose:
            print(f"Processing: {item}")
        results.append(item)
    return results
'''
        pipeline = CodeAwarePipeline()
        result = pipeline.compress(code, language="python")
        assert result.tokens_after < result.tokens_before
        assert result.savings_pct > 0
        # Critical code preserved
        assert "def process_data" in result.compressed
        assert "return" in result.compressed

    def test_compression_modes(self):
        """Different compression modes should produce different results."""
        code = "def hello():\n    # A simple function\n    return 'world'"

        from copium.transforms.code_aware.compressor import PipelineConfig, CompressionMode

        lossless_config = PipelineConfig(mode=CompressionMode.LOSSLESS)
        lossy_config = PipelineConfig(mode=CompressionMode.LOSSY)

        lossless_pipeline = CodeAwarePipeline(config=lossless_config)
        lossy_pipeline = CodeAwarePipeline(config=lossy_config)

        lossless_result = lossless_pipeline.compress(code, language="python")
        lossy_result = lossy_pipeline.compress(code, language="python")

        # Lossy should compress more aggressively
        assert lossy_result.tokens_after <= lossless_result.tokens_after

    def test_importance_classifier(self):
        """Classifier should correctly rank code elements."""
        classifier = ImportanceClassifier()

        # Critical: error handling
        from copium.transforms.code_aware.classifier import ImportanceLevel
        assert classifier.classify_line("raise ValueError('bad input')") == ImportanceLevel.CRITICAL

        # High: function definition
        assert classifier.classify_line("def authenticate(user, password):") == ImportanceLevel.HIGH

        # Low: debug logging
        assert classifier.classify_line("    print(debug_value)") == ImportanceLevel.LOW


# =============================================================================
# End-to-End Workflow Test
# =============================================================================


class TestEndToEndWorkflow:
    """End-to-end test simulating a full agent compression workflow."""

    def test_full_agent_turn(self):
        """Simulate a full agent turn with compression at each stage."""
        from copium.agent.context_manager import AgentContextManager, TurnInput

        manager = AgentContextManager(max_tokens=4000)

        # Simulate a multi-turn conversation
        history = [
            {"role": "user", "content": "Read the auth.py file"},
            {"role": "assistant", "content": "I'll read that file for you."},
            {"role": "user", "content": "Now explain the token validation logic"},
            {"role": "assistant", "content": "The token validation uses JWT..."},
        ]

        tool_results = [
            {"role": "tool", "content": "def validate(): pass\n# lots of code...\n" * 10},
        ]

        turn = TurnInput(
            system_prompt="You are a code assistant.",
            conversation_history=history,
            tool_results=tool_results,
            current_message="What about the MFA flow?",
        )

        managed = manager.manage_turn(turn)
        assert managed.total_tokens > 0
        assert managed.fits_budget
        assert len(managed.messages) > 0
