"""Tests for code-aware compression pipeline."""

from __future__ import annotations

import pytest

from copium.transforms.code_aware.classifier import (
    ImportanceClassifier,
    ImportanceLevel,
)
from copium.transforms.code_aware.compressor import (
    CodeAwarePipeline,
    CompressionMode,
    PipelineConfig,
)
from copium.transforms.code_aware.languages import (
    GenericStrategy,
    JavaScriptStrategy,
    PythonStrategy,
    RustStrategy,
    get_strategy,
)


# =============================================================================
# Classifier Tests
# =============================================================================


class TestImportanceClassifier:
    """Tests for ImportanceClassifier."""

    def setup_method(self):
        self.classifier = ImportanceClassifier()

    def test_critical_line_detection(self):
        """Error handling and control flow are critical."""
        assert self.classifier.classify_line("raise ValueError('bad')") == ImportanceLevel.CRITICAL
        assert self.classifier.classify_line("    return result") == ImportanceLevel.CRITICAL
        assert self.classifier.classify_line("try:") == ImportanceLevel.CRITICAL
        assert self.classifier.classify_line("except Exception as e:") == ImportanceLevel.CRITICAL

    def test_high_importance_lines(self):
        """Function definitions and imports are high importance."""
        assert self.classifier.classify_line("def process_data(items):") == ImportanceLevel.HIGH
        assert self.classifier.classify_line("import os") == ImportanceLevel.HIGH
        assert self.classifier.classify_line("from typing import List") == ImportanceLevel.HIGH
        assert self.classifier.classify_line("class MyClass:") == ImportanceLevel.HIGH

    def test_low_importance_lines(self):
        """Debug logging and TODOs are low importance."""
        assert self.classifier.classify_line("# TODO: fix this later") == ImportanceLevel.LOW
        assert self.classifier.classify_line("    print(debug_value)") == ImportanceLevel.LOW
        assert self.classifier.classify_line("    pass") == ImportanceLevel.LOW

    def test_empty_line_is_low(self):
        assert self.classifier.classify_line("") == ImportanceLevel.LOW
        assert self.classifier.classify_line("   ") == ImportanceLevel.LOW

    def test_classify_block_exported(self):
        """Exported symbols get higher importance."""
        code = "def helper():\n    return 42"
        result = self.classifier.classify_block(
            code, symbol_name="helper", is_exported=True, references=5
        )
        assert result.level >= ImportanceLevel.MEDIUM

    def test_classify_block_test(self):
        """Test functions get lower importance."""
        code = "def test_something():\n    assert True"
        result = self.classifier.classify_block(
            code, symbol_name="test_something", is_test=True
        )
        # Tests should not be CRITICAL
        assert result.level <= ImportanceLevel.HIGH

    def test_classify_block_private(self):
        """Private symbols get reduced importance."""
        code = "def _internal():\n    pass"
        result = self.classifier.classify_block(
            code, symbol_name="_internal", references=0
        )
        assert result.level <= ImportanceLevel.HIGH


# =============================================================================
# Language Strategy Tests
# =============================================================================


class TestPythonStrategy:
    """Tests for Python-specific compression."""

    def setup_method(self):
        self.strategy = PythonStrategy()

    def test_docstring_critical_preserved(self):
        doc = '"""Process data and return results."""'
        assert self.strategy.compress_docstring(doc, ImportanceLevel.CRITICAL) == doc

    def test_docstring_high_first_line(self):
        doc = '"""Process data.\n\n    Args:\n        x: input\n    """'
        result = self.strategy.compress_docstring(doc, ImportanceLevel.HIGH)
        assert "Process data" in result
        assert "Args" not in result

    def test_docstring_low_removed(self):
        doc = '"""Some docstring."""'
        result = self.strategy.compress_docstring(doc, ImportanceLevel.LOW)
        assert result == ""

    def test_comment_medium_removes_trivial(self):
        assert self.strategy.compress_comment("# ----------", ImportanceLevel.MEDIUM) == ""
        assert self.strategy.compress_comment("# TODO: fix", ImportanceLevel.MEDIUM) == ""

    def test_body_medium_compressed(self):
        body = "    x = 1\n    y = 2\n    z = 3\n    return x + y + z"
        result = self.strategy.compress_body(body, "def add():", ImportanceLevel.MEDIUM)
        assert "return" in result
        assert "compressed" in result

    def test_body_critical_preserved(self):
        body = "    x = 1\n    return x"
        assert self.strategy.compress_body(body, "def f():", ImportanceLevel.CRITICAL) == body


class TestJavaScriptStrategy:
    """Tests for JavaScript compression."""

    def setup_method(self):
        self.strategy = JavaScriptStrategy()

    def test_jsdoc_high_keeps_description(self):
        doc = "/**\n * Process data items.\n * @param {Array} items\n * @returns {Array}\n */"
        result = self.strategy.compress_docstring(doc, ImportanceLevel.HIGH)
        assert "Process data" in result

    def test_body_low_minimal(self):
        body = "  const x = 1;\n  const y = 2;\n  return x + y;"
        result = self.strategy.compress_body(body, "function add()", ImportanceLevel.LOW)
        assert "..." in result


class TestRustStrategy:
    """Tests for Rust compression."""

    def setup_method(self):
        self.strategy = RustStrategy()

    def test_safety_comments_preserved(self):
        comment = "// SAFETY: pointer is valid for 'a lifetime"
        result = self.strategy.compress_comment(comment, ImportanceLevel.MEDIUM)
        assert "SAFETY" in result

    def test_regular_comment_removed_at_medium(self):
        comment = "// just a regular comment"
        result = self.strategy.compress_comment(comment, ImportanceLevel.MEDIUM)
        assert result == ""


class TestGetStrategy:
    """Tests for strategy dispatch."""

    def test_python(self):
        assert isinstance(get_strategy("python"), PythonStrategy)

    def test_javascript(self):
        assert isinstance(get_strategy("javascript"), JavaScriptStrategy)

    def test_typescript_uses_js(self):
        assert isinstance(get_strategy("typescript"), JavaScriptStrategy)

    def test_rust(self):
        assert isinstance(get_strategy("rust"), RustStrategy)

    def test_unknown_uses_generic(self):
        assert isinstance(get_strategy("haskell"), GenericStrategy)


# =============================================================================
# Pipeline Integration Tests
# =============================================================================


class TestCodeAwarePipeline:
    """Integration tests for the full pipeline."""

    def setup_method(self):
        self.pipeline = CodeAwarePipeline()

    def test_empty_input(self):
        result = self.pipeline.compress("", language="python")
        assert result.tokens_before == 0
        assert result.tokens_after == 0

    def test_python_compression(self):
        code = '''import os
from typing import List

def process_items(items: List[str]) -> List[str]:
    """Process a list of items and return filtered results.

    Args:
        items: Input list of strings.

    Returns:
        Filtered list with processed items.
    """
    results = []
    for item in items:
        # Skip empty items
        if not item:
            continue
        # Normalize the item
        processed = item.strip().lower()
        # Add to results if valid
        if len(processed) > 0:
            results.append(processed)
    return results

def _helper():
    """Internal helper function."""
    # TODO: implement this
    pass
'''
        result = self.pipeline.compress(code, language="python")
        assert result.tokens_after <= result.tokens_before
        assert result.language == "python"
        assert result.duration_ms >= 0
        # Imports should be preserved
        assert "import os" in result.compressed
        assert "from typing import List" in result.compressed

    def test_lossless_mode_preserves_all(self):
        config = PipelineConfig(mode=CompressionMode.LOSSLESS)
        pipeline = CodeAwarePipeline(config=config)
        code = "def hello():\n    return 'world'"
        result = pipeline.compress(code, language="python")
        assert result.compressed == code

    def test_archive_mode_aggressive(self):
        config = PipelineConfig(mode=CompressionMode.ARCHIVE)
        pipeline = CodeAwarePipeline(config=config)
        code = '''def long_function():
    """Very long docstring that goes on and on."""
    x = 1
    y = 2
    z = 3
    return x + y + z
'''
        result = pipeline.compress(code, language="python")
        assert result.tokens_after <= result.tokens_before

    def test_compression_ratio_positive(self):
        """Pipeline should achieve meaningful compression on verbose code."""
        code = '''
# ============================================================
# Module: data_processor
# ============================================================
# This module handles all data processing tasks
# for the application.
# ============================================================

import json
import os
from typing import Any, Dict, List, Optional

def process_data(
    input_data: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Process input data according to configuration.

    This function takes a list of dictionaries representing data records
    and processes them according to the provided configuration. If no
    configuration is provided, default settings are used.

    Args:
        input_data: List of data records to process.
        config: Optional configuration dictionary.

    Returns:
        List of processed data records.

    Raises:
        ValueError: If input_data is empty.
        TypeError: If input_data contains non-dict items.
    """
    # Validate input
    if not input_data:
        raise ValueError("input_data cannot be empty")

    # Apply default config
    if config is None:
        config = {"mode": "default", "verbose": False}

    # Process each record
    results = []
    for i, record in enumerate(input_data):
        # Log progress
        print(f"Processing record {i + 1}/{len(input_data)}")

        # Validate record type
        if not isinstance(record, dict):
            raise TypeError(f"Expected dict, got {type(record)}")

        # Apply transformations
        processed = {}
        for key, value in record.items():
            # Skip internal keys
            if key.startswith("_"):
                continue
            # Normalize string values
            if isinstance(value, str):
                processed[key] = value.strip().lower()
            else:
                processed[key] = value

        results.append(processed)

    return results
'''
        config = PipelineConfig(mode=CompressionMode.HYBRID)
        pipeline = CodeAwarePipeline(config=config)
        result = pipeline.compress(code, language="python")
        # Should save at least 10% on verbose code
        assert result.savings_pct > 10

    def test_ccr_key_generated(self):
        """CCR key should be generated when compression saves tokens."""
        config = PipelineConfig(enable_ccr=True, mode=CompressionMode.HYBRID)
        pipeline = CodeAwarePipeline(config=config)
        code = '''def verbose():
    """A very verbose docstring that goes on for many lines.

    This is filler text to ensure compression happens.
    More filler text here.
    And even more text.
    """
    # TODO: remove this debug code
    print("debug: entering function")
    x = compute()
    print(f"debug: x = {x}")
    return x
'''
        result = pipeline.compress(code, language="python")
        if result.tokens_saved > 0:
            assert result.ccr_key is not None
