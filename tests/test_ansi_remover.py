"""Tests for the ANSIRemover transform."""

from __future__ import annotations

import pytest

from copium.transforms.ansi_remover import (
    ANSIRemover,
    ANSIRemoverConfig,
    strip_ansi,
    strip_progress_bars,
    strip_spinners,
)


class TestStripAnsi:
    """Unit tests for strip_ansi utility."""

    def test_no_ansi_passthrough(self):
        text = "hello world\nline 2"
        assert strip_ansi(text) == text

    def test_strip_sgr_colors(self):
        text = "\x1b[31mred text\x1b[0m normal"
        assert strip_ansi(text) == "red text normal"

    def test_strip_bold_underline(self):
        text = "\x1b[1mbold\x1b[22m \x1b[4munderline\x1b[24m"
        assert strip_ansi(text) == "bold underline"

    def test_strip_256_color(self):
        text = "\x1b[38;5;196mred\x1b[0m"
        assert strip_ansi(text) == "red"

    def test_strip_cursor_movement(self):
        text = "\x1b[2J\x1b[Hcontent\x1b[10A"
        assert strip_ansi(text) == "content"

    def test_strip_osc_window_title(self):
        text = "\x1b]0;My Terminal\x07actual content"
        assert strip_ansi(text) == "actual content"

    def test_mixed_ansi(self):
        text = "\x1b[1;32m✓\x1b[0m Tests passed \x1b[33m(5 suites)\x1b[0m"
        assert strip_ansi(text) == "✓ Tests passed (5 suites)"

    def test_empty_string(self):
        assert strip_ansi("") == ""


class TestStripSpinners:
    """Unit tests for strip_spinners."""

    def test_no_cr_passthrough(self):
        text = "line1\nline2\nline3"
        assert strip_spinners(text) == text

    def test_single_cr_overwrite(self):
        text = "loading...\rdone!"
        assert strip_spinners(text) == "done!"

    def test_multiple_cr_overwrites(self):
        text = "step1\rstep2\rstep3\rfinal"
        assert strip_spinners(text) == "final"

    def test_multiline_with_cr(self):
        text = "line1\nspinner\rresult\nline3"
        assert strip_spinners(text) == "line1\nresult\nline3"


class TestANSIRemoverTransform:
    """Integration tests for the ANSIRemover transform."""

    def _make_messages(self, contents):
        messages = []
        for role, content in contents:
            messages.append({"role": role, "content": content})
        return messages

    def test_strips_tool_output_ansi(self):
        from copium.tokenizer import Tokenizer

        messages = self._make_messages([
            ("user", "run the tests"),
            ("tool", "\x1b[32m✓ test_foo passed\x1b[0m\n\x1b[31m✗ test_bar failed\x1b[0m"),
        ])
        tokenizer = Tokenizer("cl100k_base")
        remover = ANSIRemover()
        result = remover.apply(messages, tokenizer)

        assert "ansi_remover" in result.transforms_applied
        assert "\x1b" not in result.messages[1]["content"]
        assert "test_foo passed" in result.messages[1]["content"]

    def test_skips_content_without_ansi(self):
        from copium.tokenizer import Tokenizer

        messages = self._make_messages([
            ("user", "what is the meaning of life?"),
            ("assistant", "42"),
        ])
        tokenizer = Tokenizer("cl100k_base")
        remover = ANSIRemover()
        result = remover.apply(messages, tokenizer)

        assert result.transforms_applied == []

    def test_respects_frozen_messages(self):
        from copium.tokenizer import Tokenizer

        messages = self._make_messages([
            ("tool", "\x1b[31mfrozen error output here\x1b[0m"),
            ("tool", "\x1b[31mmutable error output here\x1b[0m"),
        ])
        tokenizer = Tokenizer("cl100k_base")
        remover = ANSIRemover()
        result = remover.apply(messages, tokenizer, frozen_message_count=1)

        assert "\x1b" in result.messages[0]["content"]
        assert "\x1b" not in result.messages[1]["content"]

    def test_disabled_config(self):
        from copium.tokenizer import Tokenizer

        messages = self._make_messages([
            ("tool", "\x1b[31merror output content here\x1b[0m"),
        ])
        tokenizer = Tokenizer("cl100k_base")
        config = ANSIRemoverConfig(enabled=False)
        remover = ANSIRemover(config)
        result = remover.apply(messages, tokenizer)

        assert result.transforms_applied == []
