"""Tests for error-driven compression (ErrorCompressor)."""

from __future__ import annotations

import pytest

from copium.config import CopiumConfig, ErrorCompressorConfig
from copium.transforms.error_compressor import (
    ErrorCard,
    ErrorCompressor,
    _collapse_identical_errors,
    _compress_stack_trace,
    _detect_error_type,
    _extract_file_line,
    _extract_next_actions,
    _extract_stack_frames,
    _is_error_line,
    _is_framework_frame,
    _is_security_warning,
)


class TestErrorCard:
    """Test ErrorCard dataclass."""

    def test_basic_marker(self):
        card = ErrorCard(
            error_type="TypeError",
            message="cannot concatenate str and int",
            file="main.py",
            line=42,
        )
        marker = card.to_marker()
        assert "[Error: TypeError]" in marker
        assert "cannot concatenate str and int" in marker
        assert "main.py:42" in marker

    def test_marker_with_exit_code(self):
        card = ErrorCard(
            error_type="ExitCode2",
            message="command failed",
            exit_code=2,
        )
        marker = card.to_marker()
        assert "(exit 2)" in marker

    def test_marker_with_frames(self):
        card = ErrorCard(
            error_type="RuntimeError",
            message="connection refused",
            stack_frames=["src/api.py:15", "src/main.py:8"],
        )
        marker = card.to_marker()
        assert "src/api.py:15" in marker
        assert "src/main.py:8" in marker
        assert "→" in marker

    def test_marker_with_next_actions(self):
        card = ErrorCard(
            error_type="CommandNotFound",
            message="command not found: mytool",
            next_actions=["Verify command exists and is in PATH"],
        )
        marker = card.to_marker()
        assert "NEXT:" in marker
        assert "Verify command exists and is in PATH" in marker

    def test_marker_truncation(self):
        card = ErrorCard(
            error_type="Error",
            message="x" * 2000,
        )
        marker = card.to_marker(max_tokens=50)
        assert len(marker) < 2000


class TestDetectionHelpers:
    """Test helper functions for error detection."""

    def test_is_error_line_python(self):
        assert _is_error_line("TypeError: 'int' object is not subscriptable")
        assert _is_error_line("FileNotFoundError: No such file")
        assert _is_error_line("ERROR: something failed")
        assert not _is_error_line("All tests passed")
        assert not _is_error_line("")

    def test_is_error_line_node(self):
        assert _is_error_line("Error: Cannot find module 'foo'")
        assert _is_error_line("FATAL: out of memory")

    def test_is_framework_frame_node(self):
        assert _is_framework_frame("at node_modules/express/lib/router.js:10:5")
        assert _is_framework_frame("at Module._compile (internal/modules/cjs/loader.js:999:30)")
        assert not _is_framework_frame("at src/app.ts:42:5")

    def test_is_framework_frame_python(self):
        assert _is_framework_frame('File "/usr/lib/python3.10/site-packages/flask/app.py", line 1')
        assert not _is_framework_frame('File "/home/user/project/main.py", line 10')

    def test_is_security_warning(self):
        assert _is_security_warning("CVE-2024-12345: Critical vulnerability")
        assert _is_security_warning("GHSA-xxxx-yyyy-zzzz: Security advisory")
        assert not _is_security_warning("Regular error message")

    def test_extract_file_line(self):
        assert _extract_file_line("at src/app.ts:42:5") == ("src/app.ts", 42)
        assert _extract_file_line('File "main.py", line 10') == ("main.py", 10)
        assert _extract_file_line("no file here") == (None, None)

    def test_detect_error_type_python(self):
        assert _detect_error_type("TypeError: foo") == "TypeError"
        assert _detect_error_type("FileNotFoundError: bar") == "FileNotFoundError"
        assert _detect_error_type("ValueError: baz") == "ValueError"

    def test_detect_error_type_exit_code(self):
        assert _detect_error_type("exit code 127") == "CommandNotFound"
        assert _detect_error_type("exit code 137") == "OOMKilled"
        assert _detect_error_type("exit code 139") == "Segfault"
        assert _detect_error_type("exit code 1") == "GenericError"
        assert _detect_error_type("exit code 42") == "ExitCode42"

    def test_detect_error_type_build(self):
        assert _detect_error_type("BUILD FAILED") == "BuildError"
        assert _detect_error_type("Compilation failed") == "CompilationError"

    def test_extract_stack_frames_python(self):
        text = """Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/flask/app.py", line 200, in handle_exception
    return self.handle_exception(e)
  File "/home/user/project/main.py", line 42, in handler
    result = process(data)
  File "/home/user/project/utils.py", line 15, in process
    return data[0]"""
        frames = _extract_stack_frames(text)
        assert len(frames) <= 3
        # Should skip framework frames
        for frame in frames:
            assert "site-packages" not in frame

    def test_extract_stack_frames_node(self):
        text = """    at Server.listen (/usr/lib/node_modules/express/lib/server.js:100:5)
    at Object.<anonymous> (/home/user/project/src/app.ts:15:10)
    at Module._compile (internal/modules/cjs/loader.js:999:30)"""
        frames = _extract_stack_frames(text)
        assert len(frames) <= 3
        for frame in frames:
            assert "node_modules" not in frame

    def test_extract_next_actions_type_error(self):
        actions = _extract_next_actions("TypeError", None, None)
        assert any("Check variable" in a for a in actions)

    def test_extract_next_actions_command_not_found(self):
        actions = _extract_next_actions("CommandNotFound", None, None)
        assert any("Verify command" in a for a in actions)

    def test_extract_next_actions_with_file(self):
        actions = _extract_next_actions("Error", "main.py", 42)
        assert any("Read main.py:42" in a for a in actions)


class TestCompressStackTrace:
    """Test stack trace compression."""

    def test_python_traceback(self):
        text = """Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/flask/app.py", line 200, in handle_exception
  File "/home/user/project/main.py", line 42, in handler
    result = process(data)
  File "/home/user/project/utils.py", line 15, in process
    return data[0]
TypeError: 'int' object is not subscriptable"""
        result = _compress_stack_trace(text, max_frames=2)
        assert "site-packages" not in result
        assert "main.py" in result or "utils.py" in result
        assert "framework" in result.lower() or "internal" in result.lower()

    def test_node_stack_trace(self):
        text = """TypeError: Cannot read property 'map' of undefined
    at Server.listen (/usr/lib/node_modules/express/lib/server.js:100:5)
    at Object.<anonymous> (/home/user/project/src/app.ts:15:10)
    at Module._compile (internal/modules/cjs/loader.js:999:30)
    at Function.Module._load (internal/modules/cjs/loader.js:850:27)"""
        result = _compress_stack_trace(text, max_frames=2)
        assert "node_modules" not in result
        assert "app.ts" in result

    def test_no_stack_trace(self):
        text = "Just a regular error message"
        result = _compress_stack_trace(text)
        assert result == text


class TestCollapseIdenticalErrors:
    """Test collapsing repeated identical error lines."""

    def test_basic_collapse(self):
        text = "error: unused variable x\nerror: unused variable x\nerror: unused variable x"
        result = _collapse_identical_errors(text)
        assert "x3)" in result or "x 3)" in result

    def test_no_collapse_single(self):
        text = "error: unused variable x\nerror: unused variable y"
        result = _collapse_identical_errors(text)
        assert "x3)" not in result

    def test_preserve_unique_lines(self):
        text = "error: line1\nerror: line2\nerror: line2\nerror: line2\nerror: line3"
        result = _collapse_identical_errors(text)
        assert "line1" in result
        assert "line3" in result


class TestErrorCompressorTransform:
    """Test the ErrorCompressor transform end-to-end."""

    def _make_tool_output(self, content: str) -> dict:
        return {"role": "tool", "content": content}

    def _make_user_msg(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def _make_assistant_msg(self, content: str) -> dict:
        return {"role": "assistant", "content": content}

    def _run_transform(self, messages, config=None):
        from copium.tokenizers import get_tokenizer
        from copium.tokenizer import Tokenizer

        tc = get_tokenizer("gpt-4")
        tokenizer = Tokenizer(tc, "gpt-4")
        compressor = ErrorCompressor(config)
        return compressor.apply(messages, tokenizer)

    def test_compressed_python_traceback(self):
        traceback = """Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/flask/app.py", line 200, in handle_exception
  File "/home/user/project/main.py", line 42, in handler
    result = process(data)
  File "/home/user/project/utils.py", line 15, in process
    return data[0]
TypeError: 'int' object is not subscriptable

During handling of the above exception, another exception occurred:
Traceback (most recent call last):
  File "/home/user/project/main.py", line 50, in run
    app.run()
  File "/usr/lib/python3.10/site-packages/flask/app.py", line 1000, in run
    return self.handle_exception(e)
  File "/home/user/project/main.py", line 42, in handler
    result = process(data)"""
        messages = [
            self._make_user_msg("Run the app"),
            self._make_tool_output(traceback),
        ]
        result = self._run_transform(messages)
        # Should have compressed the tool output
        assert len(result.messages[1]["content"]) < len(traceback)

    def test_compressed_node_error(self):
        error = """Error: Cannot find module 'express'
    at Function.Module._resolveFilename (internal/modules/cjs/loader.js:999:15)
    at Function.Module._load (internal/modules/cjs/loader.js:850:27)
    at Module.require (internal/modules/cjs/loader.js:1038:19)
    at Object.<anonymous> (/home/user/project/src/app.ts:1:10)"""
        messages = [
            self._make_user_msg("Start the server"),
            self._make_tool_output(error),
        ]
        result = self._run_transform(messages)
        assert len(result.messages[1]["content"]) < len(error)

    def test_compressed_exit_code(self):
        output = """$ npm test
FAIL src/app.test.ts
● Test suite failed to run

Jest encountered a syntax error

SyntaxError: Unexpected token

> 1 | const x = ;
    |           ^
  2 |

Tests: 0 failed, 0 total
Ran all test suites.

 exited with code 1"""
        messages = [
            self._make_user_msg("Run tests"),
            self._make_tool_output(output),
        ]
        result = self._run_transform(messages)
        # Should have compressed
        assert result.transforms_applied

    def test_no_compression_short_output(self):
        short_error = "Error: file not found"
        messages = [
            self._make_user_msg("Do something"),
            self._make_tool_output(short_error),
        ]
        result = self._run_transform(messages)
        # Too short to compress
        assert not result.transforms_applied

    def test_no_compression_no_error(self):
        success = """All tests passed!
12 tests, 12 passed, 0 failed
Duration: 1.2s"""
        messages = [
            self._make_user_msg("Run tests"),
            self._make_tool_output(success),
        ]
        result = self._run_transform(messages)
        assert not result.transforms_applied

    def test_preserves_user_messages(self):
        traceback = """Traceback (most recent call last):
  File "/home/user/project/main.py", line 42
    result = process(data)
TypeError: 'int' object is not subscriptable

  File "/usr/lib/python3.10/site-packages/flask/app.py", line 200
    pass"""
        messages = [
            self._make_user_msg("Run the app"),
            self._make_assistant_msg("Running now..."),
            self._make_tool_output(traceback),
        ]
        result = self._run_transform(messages)
        # User message should be unchanged
        assert result.messages[0]["content"] == "Run the app"
        assert result.messages[1]["content"] == "Running now..."

    def test_preserves_security_warnings(self):
        output = """CVE-2024-12345: Critical vulnerability in lodash
Upgrade to lodash 4.17.21 or later.
See https://nvd.nist.gov/vuln/detail/CVE-2024-12345"""
        messages = [
            self._make_user_msg("Check deps"),
            self._make_tool_output(output),
        ]
        result = self._run_transform(messages)
        # Security warnings should be preserved
        content = result.messages[1]["content"]
        assert "CVE-2024-12345" in content

    def test_disabled_config(self):
        config = ErrorCompressorConfig(enabled=False)
        traceback = """Traceback (most recent call last):
  File "/home/user/project/main.py", line 42
TypeError: 'int' object is not subscriptable"""
        messages = [
            self._make_user_msg("Run"),
            self._make_tool_output(traceback),
        ]
        result = self._run_transform(messages, config)
        assert not result.transforms_applied
        # Content unchanged
        assert result.messages[1]["content"] == traceback

    def test_collapse_repeated_errors(self):
        # Repeated identical errors — must exceed min_length_to_compress (150)
        repeated = "\n".join(["error: unused variable 'x' in module 'utils' please remove it"] * 8)
        messages = [
            self._make_user_msg("Run"),
            self._make_tool_output(repeated),
        ]
        result = self._run_transform(messages)
        # Should have collapsed
        content = result.messages[1]["content"]
        assert "x8)" in content

    def test_tokens_reduced(self):
        traceback = """Traceback (most recent call last):
  File "/usr/lib/python3.10/site-packages/flask/app.py", line 200, in handle_exception
  File "/usr/lib/python3.10/site-packages/jinja2/environment.py", line 100, in handle_exception
  File "/usr/lib/python3.10/site-packages/werkzeug/exceptions.py", line 50, in handle_exception
  File "/home/user/project/main.py", line 42, in handler
    result = process(data)
  File "/home/user/project/utils.py", line 15, in process
    return data[0]
TypeError: 'int' object is not subscriptable"""
        messages = [
            self._make_user_msg("Run"),
            self._make_tool_output(traceback),
        ]
        result = self._run_transform(messages)
        assert result.tokens_after < result.tokens_before
