"""Tests for FileReadCompressor.

Covers:
- Language detection
- Python structure extraction (regex fallback)
- Generic language structure extraction
- Region extraction
- Truncation fallback
- Compression ratio calculations
- Transform.apply() integration
"""

from __future__ import annotations

import pytest

from copium.transforms.file_read_compressor import (
    FileReadCompressor,
    FileReadCompressorConfig,
    FileReadCompressionResult,
    FileReadCompressorMode,
    _detect_language,
    _extract_structure_python,
    _extract_structure_generic,
    _extract_region,
    _format_structure_summary,
)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_python_extension(self):
        assert _detect_language("main.py") == "python"

    def test_typescript_extension(self):
        assert _detect_language("index.ts") == "typescript"

    def test_rust_extension(self):
        assert _detect_language("lib.rs") == "rust"

    def test_go_extension(self):
        assert _detect_language("main.go") == "go"

    def test_unknown_extension(self):
        assert _detect_language("README") is None

    def test_none_path(self):
        assert _detect_language(None) is None

    @pytest.mark.parametrize("ext,lang", [
        (".py", "python"),
        (".js", "javascript"),
        (".jsx", "javascript"),
        (".tsx", "typescript"),
        (".go", "go"),
        (".rs", "rust"),
        (".java", "java"),
        (".c", "c"),
        (".cpp", "cpp"),
        (".rb", "ruby"),
        (".sh", "bash"),
    ])
    def test_all_extensions(self, ext: str, lang: str):
        assert _detect_language(f"test{ext}") == lang


# ---------------------------------------------------------------------------
# Python structure extraction
# ---------------------------------------------------------------------------


class TestExtractStructurePython:
    def test_extracts_classes(self):
        code = '''
class MyClass:
    def method(self):
        pass

class Another:
    pass
'''
        items = _extract_structure_python(code)
        names = [i.name for i in items]
        assert "MyClass" in names
        assert "Another" in names

    def test_extracts_functions(self):
        code = '''
def hello():
    pass

def world(x, y):
    return x + y
'''
        items = _extract_structure_python(code)
        names = [i.name for i in items]
        assert "hello" in names
        assert "world" in names

    def test_extracts_nested_functions(self):
        code = '''
class Outer:
    def method(self):
        def inner():
            pass
        return inner
'''
        items = _extract_structure_python(code)
        # Should extract at least the class and outer method
        names = [i.name for i in items]
        assert "Outer" in names

    def test_empty_code(self):
        assert _extract_structure_python("") == []
        assert _extract_structure_python("# just a comment") == []

    def test_multiline_signature(self):
        code = '''
def long_function(
    arg1: str,
    arg2: int,
    arg3: list[str],
) -> bool:
    return True
'''
        items = _extract_structure_python(code)
        assert len(items) == 1
        assert items[0].name == "long_function"
        assert "def long_function" in items[0].signature


# ---------------------------------------------------------------------------
# Generic language structure extraction
# ---------------------------------------------------------------------------


class TestExtractStructureGeneric:
    def test_rust_functions(self):
        code = '''
pub fn hello() {}
fn world() {}
pub struct MyStruct {}
enum MyEnum { A, B }
'''
        items = _extract_structure_generic(code, "rust")
        names = [i.name for i in items]
        assert "hello" in names
        assert "world" in names

    def test_go_functions(self):
        code = '''
func Hello() {}
func World(x int) string { return "" }
type MyStruct struct {}
'''
        items = _extract_structure_generic(code, "go")
        names = [i.name for i in items]
        assert "Hello" in names
        assert "World" in names

    def test_javascript_functions(self):
        code = '''
function hello() {}
const world = () => {}
class MyClass {}
'''
        items = _extract_structure_generic(code, "javascript")
        names = [i.name for i in items]
        assert "hello" in names
        assert "world" in names
        assert "MyClass" in names

    def test_unknown_language_returns_empty(self):
        assert _extract_structure_generic("code", "unknown_lang") == []


# ---------------------------------------------------------------------------
# Region extraction
# ---------------------------------------------------------------------------


class TestExtractRegion:
    def test_basic_region(self):
        lines = [f"line {i}" for i in range(1, 101)]
        result = _extract_region(lines, 10, 20, context_lines=2)
        assert "line 8" in result
        assert "line 10" in result
        assert "line 20" in result
        assert "line 22" in result
        assert "lines before" in result
        assert "lines after" in result

    def test_region_at_start(self):
        lines = [f"line {i}" for i in range(1, 51)]
        result = _extract_region(lines, 1, 5, context_lines=2)
        assert "lines before" not in result
        assert "line 1" in result
        assert "lines after" in result

    def test_region_at_end(self):
        lines = [f"line {i}" for i in range(1, 51)]
        result = _extract_region(lines, 45, 50, context_lines=2)
        assert "lines before" in result
        assert "line 50" in result
        assert "lines after" not in result

    def test_region_full_file(self):
        lines = [f"line {i}" for i in range(1, 11)]
        result = _extract_region(lines, 1, 10, context_lines=0)
        assert "lines before" not in result
        assert "lines after" not in result
        for i in range(1, 11):
            assert f"line {i}" in result


# ---------------------------------------------------------------------------
# Structure summary formatting
# ---------------------------------------------------------------------------


class TestFormatStructureSummary:
    def test_empty_items(self):
        assert _format_structure_summary([]) == ""

    def test_basic_summary(self):
        from copium.transforms.file_read_compressor import _ASTItem
        items = [
            _ASTItem("MyClass", "class", 1, 50, "class MyClass:"),
            _ASTItem("hello", "function", 52, 60, "def hello():"),
        ]
        result = _format_structure_summary(items, language="python")
        assert "File structure" in result
        assert "2 items" in result
        assert "class MyClass" in result
        assert "fn hello" in result

    def test_summary_with_max_items(self):
        from copium.transforms.file_read_compressor import _ASTItem
        items = [
            _ASTItem(f"func_{i}", "function", i * 10, i * 10 + 5, f"def func_{i}():")
            for i in range(50)
        ]
        result = _format_structure_summary(items, max_items=10)
        assert "50 items" in result  # Header shows total
        assert "40 more items" in result  # Shows how many omitted
        # Should only show first 10
        assert "func_9" in result
        assert "func_10" not in result


# ---------------------------------------------------------------------------
# FileReadCompressor main class
# ---------------------------------------------------------------------------


class TestFileReadCompressor:
    def test_short_file_passed_through(self):
        compressor = FileReadCompressor()
        short_content = "line 1\nline 2\nline 3"
        result = compressor.compress_file_content(short_content, "test.py")
        assert result.compressed == short_content
        assert result.compression_ratio == 1.0

    def test_long_file_gets_compressed(self):
        compressor = FileReadCompressor(config=FileReadCompressorConfig(max_lines=10))
        lines = [f"line {i}" for i in range(100)]
        content = "\n".join(lines)
        result = compressor.compress_file_content(content, "test.py")
        assert result.compressed_line_count < result.original_line_count
        assert result.mode_used in (
            FileReadCompressorMode.STRUCTURE,
            FileReadCompressorMode.TRUNCATE,
        )

    def test_region_extraction_when_hint_provided(self):
        compressor = FileReadCompressor()
        lines = [f"line {i}" for i in range(250)]
        content = "\n".join(lines)
        result = compressor.compress_file_content(
            content, "test.py", start_line=50, end_line=60,
        )
        assert result.mode_used == FileReadCompressorMode.REGION
        assert "line 50" in result.compressed
        assert "line 60" in result.compressed

    def test_python_file_uses_structure_mode(self):
        compressor = FileReadCompressor(config=FileReadCompressorConfig(max_lines=5))
        code = '''
"""Module docstring."""

import os

class MyClass:
    """A class."""
    def method(self):
        pass

def hello():
    pass

def world():
    pass
'''
        result = compressor.compress_file_content(code, "test.py")
        assert result.language == "python"
        # Should extract structure items
        assert result.items_extracted >= 2

    def test_compression_ratio(self):
        result = FileReadCompressionResult(
            compressed="short",
            original_line_count=100,
            compressed_line_count=10,
            mode_used=FileReadCompressorMode.TRUNCATE,
        )
        assert result.compression_ratio == 0.1

    def test_compression_ratio_zero_lines(self):
        result = FileReadCompressionResult(
            compressed="",
            original_line_count=0,
            compressed_line_count=0,
            mode_used=FileReadCompressorMode.TRUNCATE,
        )
        assert result.compression_ratio == 1.0


# ---------------------------------------------------------------------------
# Transform.apply() integration
# ---------------------------------------------------------------------------


class TestFileReadCompressorApply:
    @pytest.fixture
    def tokenizer(self):
        from copium.providers import OpenAIProvider
        from copium.tokenizer import Tokenizer
        provider = OpenAIProvider()
        token_counter = provider.get_token_counter("gpt-4o")
        return Tokenizer(token_counter, "gpt-4o")

    def test_non_tool_messages_ignored(self, tokenizer):
        compressor = FileReadCompressor()
        messages = [{"role": "user", "content": "hello"}]
        result = compressor.apply(messages, tokenizer)
        assert result.transforms_applied == []
        assert result.messages == messages

    def test_short_tool_result_ignored(self, tokenizer):
        compressor = FileReadCompressor(config=FileReadCompressorConfig(max_lines=200))
        messages = [{"role": "tool", "content": "short result"}]
        result = compressor.apply(messages, tokenizer)
        assert result.transforms_applied == []

    def test_long_tool_result_compressed(self, tokenizer):
        compressor = FileReadCompressor(config=FileReadCompressorConfig(max_lines=10))
        lines = [f"line {i}" for i in range(100)]
        messages = [{"role": "tool", "content": "\n".join(lines)}]
        result = compressor.apply(messages, tokenizer)
        assert "file_read_compressor" in result.transforms_applied
        # Content should be compressed
        assert len(result.messages[0]["content"].splitlines()) < 100
