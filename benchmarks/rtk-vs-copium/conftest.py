"""Pytest configuration for RTK vs Copium benchmarks."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark all items in this directory as benchmark tests."""
    for item in items:
        item.add_marker(pytest.mark.benchmark)
