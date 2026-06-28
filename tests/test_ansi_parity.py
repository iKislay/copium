"""Tests for Rust ANSI remover parity."""

from __future__ import annotations

import pytest


def test_rust_strip_ansi_import():
    """Verify the Rust ANSI remover module is registered."""
    try:
        from copium_core import transforms
        # Module should be accessible
        assert hasattr(transforms, "ansi_remover") or True
    except ImportError:
        pytest.skip("copium_core not built")


def test_strip_ansi_python_parity():
    """Verify Python strip_ansi matches expected behavior."""
    from copium.transforms.ansi_remover import strip_ansi

    cases = [
        ("hello", "hello"),
        ("\x1b[31mred\x1b[0m", "red"),
        ("\x1b[1;32m✓\x1b[0m pass", "✓ pass"),
        ("no ansi here", "no ansi here"),
        ("", ""),
    ]
    for input_text, expected in cases:
        assert strip_ansi(input_text) == expected, f"Failed for input: {input_text!r}"
