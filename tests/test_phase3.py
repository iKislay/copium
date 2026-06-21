"""Tests for Phase 3 features: Simulator, Grammar, Backends."""

from __future__ import annotations

import json

import pytest

from copium.grammar import (
    GrammarCompressor,
    GrammarCompressorConfig,
    GrammarType,
    detect_grammar,
    validate_and_repair,
    _validate_json,
    _repair_json,
    _validate_markdown,
    _repair_markdown,
)
from copium.simulator import (
    ContextSimulator,
    SimulationResult,
    TransformMetrics,
    RoleMetrics,
    get_model_pricing,
)
from copium.native_backends import (
    BackendCapabilities,
    BackendDetector,
    BackendHealth,
    BackendType,
)


class TestGrammarDetection:
    """Test grammar type detection."""

    def test_json_detection(self):
        assert detect_grammar('{"key": "value"}') == GrammarType.JSON
        assert detect_grammar('[1, 2, 3]') == GrammarType.JSON

    def test_markdown_detection(self):
        assert detect_grammar("# Header\n\nContent") == GrammarType.MARKDOWN
        assert detect_grammar("```python\ncode\n```") == GrammarType.MARKDOWN

    def test_code_detection(self):
        assert detect_grammar("def hello():\n    pass") == GrammarType.CODE
        assert detect_grammar("const x = 1;") == GrammarType.CODE

    def test_freeform(self):
        assert detect_grammar("just plain text") == GrammarType.FREEFORM


class TestJSONGrammar:
    """Test JSON grammar validation and repair."""

    def test_valid_json(self):
        assert _validate_json('{"key": "value"}')
        assert _validate_json('[1, 2, 3]')

    def test_invalid_json(self):
        assert not _validate_json('{"key": "value",}')
        assert not _validate_json('{key: value}')

    def test_repair_trailing_comma(self):
        repaired = _repair_json('{"key": "value",}')
        assert json.loads(repaired) == {"key": "value"}

    def test_repair_unclosed(self):
        repaired = _repair_json('{"key": "value"')
        assert json.loads(repaired) == {"key": "value"}


class TestMarkdownGrammar:
    """Test markdown grammar validation and repair."""

    def test_valid_markdown(self):
        assert _validate_markdown("# Header\n\n```python\ncode\n```")

    def test_unclosed_code_block(self):
        assert not _validate_markdown("```python\ncode")

    def test_repair_unclosed_fence(self):
        repaired = _repair_markdown("```python\ncode")
        assert repaired.count("```") % 2 == 0

    def test_header_without_space(self):
        assert not _validate_markdown("#Header")

    def test_repair_header(self):
        repaired = _repair_markdown("#Header")
        assert repaired.startswith("# Header")


class TestValidateAndRepair:
    """Test the combined validate_and_repair function."""

    def test_valid_content(self):
        is_valid, content, grammar = validate_and_repair('{"key": "value"}')
        assert is_valid
        assert grammar == GrammarType.JSON

    def test_invalid_json_auto_repair(self):
        is_valid, content, grammar = validate_and_repair('{"key": "value",}')
        assert is_valid
        assert json.loads(content) == {"key": "value"}

    def test_freeform_always_valid(self):
        is_valid, content, grammar = validate_and_repair("plain text")
        assert is_valid
        assert grammar == GrammarType.FREEFORM


class TestGrammarCompressor:
    """Test grammar-constrained compression."""

    def test_json_compression_valid(self):
        config = GrammarCompressorConfig()
        compressor = GrammarCompressor(config)

        def lossy_compress(content):
            # Simulate a lossy compressor that might break JSON
            return '{"key": "compressed",}'

        compressed, grammar, was_valid = compressor.compress(
            '{"key": "original value", "extra": "data"}',
            compressor=lossy_compress,
        )
        # Should be repaired
        assert was_valid
        assert grammar == GrammarType.JSON
        parsed = json.loads(compressed)
        assert "key" in parsed

    def test_compression_preserves_structure(self):
        config = GrammarCompressorConfig()
        compressor = GrammarCompressor(config)

        original = "# Hello\n\nSome content"
        compressed, grammar, was_valid = compressor.compress(original)
        assert was_valid
        assert grammar == GrammarType.MARKDOWN
        assert "# Hello" in compressed

    def test_disabled_config(self):
        config = GrammarCompressorConfig(enabled=False)
        compressor = GrammarCompressor(config)
        content = '{"key": "value",}'
        compressed, grammar, was_valid = compressor.compress(content)
        assert was_valid  # Not validated when disabled


class TestModelPricing:
    """Test model pricing lookup."""

    def test_known_models(self):
        input_cost, output_cost = get_model_pricing("gpt-4o")
        assert input_cost == 0.0025
        assert output_cost == 0.01

    def test_partial_match(self):
        input_cost, output_cost = get_model_pricing("my-gpt-4o-deployment")
        assert input_cost == 0.0025

    def test_unknown_model_default(self):
        input_cost, output_cost = get_model_pricing("some-unknown-model")
        assert input_cost > 0  # Should return default pricing


class TestTransformMetrics:
    """Test TransformMetrics."""

    def test_savings_pct(self):
        m = TransformMetrics(
            name="test", tokens_before=1000, tokens_after=800,
            tokens_saved=200, messages_affected=5, duration_ms=1.5,
        )
        assert m.savings_pct == 20.0

    def test_zero_before(self):
        m = TransformMetrics(
            name="test", tokens_before=0, tokens_after=0,
            tokens_saved=0, messages_affected=0, duration_ms=0.0,
        )
        assert m.savings_pct == 0.0


class TestRoleMetrics:
    """Test RoleMetrics."""

    def test_tokens_saved(self):
        r = RoleMetrics(role="tool", count=10, tokens_before=5000, tokens_after=3000)
        assert r.tokens_saved == 2000
        assert r.savings_pct == 40.0


class TestSimulationResult:
    """Test SimulationResult."""

    def test_format_report(self):
        result = SimulationResult(
            tokens_before=10000,
            tokens_after=6000,
            tokens_saved=4000,
            total_duration_ms=15.5,
            transforms=[],
            roles=[],
            model="gpt-4o",
            cost_per_1k_input=0.0025,
            cost_per_1k_output=0.01,
            estimated_input_cost_before=0.025,
            estimated_input_cost_after=0.015,
            estimated_monthly_savings=30.0,
            warnings=[],
            transforms_applied=[],
        )
        report = result.format_report()
        assert "CONTEXT WINDOW SIMULATION REPORT" in report
        assert "4,000" in report
        assert "40.0%" in report


class TestBackendCapabilities:
    """Test BackendCapabilities."""

    def test_to_dict(self):
        caps = BackendCapabilities(
            backend=BackendType.OLLAMA,
            model_name="llama3",
            max_context_length=8192,
        )
        d = caps.to_dict()
        assert d["backend"] == "ollama"
        assert d["model_name"] == "llama3"
        assert d["max_context_length"] == 8192


class TestBackendHealth:
    """Test BackendHealth."""

    def test_healthy(self):
        h = BackendHealth(is_healthy=True, latency_ms=50.0)
        d = h.to_dict()
        assert d["healthy"] is True
        assert d["latency_ms"] == 50.0

    def test_unhealthy(self):
        h = BackendHealth(is_healthy=False, error="Connection refused")
        d = h.to_dict()
        assert d["healthy"] is False
        assert "Connection refused" in d["error"]


class TestBackendDetector:
    """Test BackendDetector."""

    def test_unknown_without_url(self):
        detector = BackendDetector()
        caps = detector.detect()
        assert caps.backend == BackendType.UNKNOWN

    def test_health_check_no_url(self):
        detector = BackendDetector()
        health = detector.health_check()
        assert not health.is_healthy
        assert "No URL" in health.error
