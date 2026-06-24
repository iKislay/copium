"""Tests for :mod:`copium.cli.explain` — the ``copium explain`` command.

Covers:
- Offline path (reads from JSONL)
- JSON output mode
- Cost estimation (provider pricing + fallback)
- Timestamp formatting
- Token formatting
- Error handling for missing request IDs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from copium.cli.explain import (
    _fmt_ts,
    _fmt_tokens,
    _rough_usd,
    _load_entry_offline,
    explain,
)


# ── _fmt_tokens ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "0"),
        (999, "999"),
        (1000, "1,000"),
        (12345, "12,345"),
        (999999, "999,999"),
        (1_000_000, "1.0M"),
        (2_500_000, "2.5M"),
        (15_000_000, "15.0M"),
    ],
)
def test_fmt_tokens(n: int, expected: str) -> None:
    assert _fmt_tokens(n) == expected


# ── _fmt_ts ──────────────────────────────────────────────────────────


def test_fmt_ts_iso_utc() -> None:
    assert _fmt_ts("2026-06-23T19:04:31Z") == "19:04:31"


def test_fmt_ts_iso_with_offset() -> None:
    assert _fmt_ts("2026-06-23T19:04:31+00:00") == "19:04:31"


def test_fmt_ts_invalid() -> None:
    assert _fmt_ts("not-a-date") == "not-a-date"


def test_fmt_ts_empty() -> None:
    assert _fmt_ts("") == ""


# ── _rough_usd / _estimate_rate ──────────────────────────────────────


def test_rough_usd_opus() -> None:
    result = _rough_usd(1000, "claude-opus-4")
    assert "$0.015" in result


def test_rough_usd_sonnet() -> None:
    result = _rough_usd(1000, "claude-sonnet-4")
    assert "$0.003" in result


def test_rough_usd_haiku() -> None:
    result = _rough_usd(1000, "claude-haiku-4")
    # Anthropic pattern match: haiku = $0.80/MTok input
    assert "$0.0008" in result


def test_rough_usd_gpt4() -> None:
    result = _rough_usd(1000, "gpt-4o")
    # OpenAI pricing: gpt-4o = $2.50/MTok input
    assert "$0.0025" in result


def test_rough_usd_unknown_model() -> None:
    result = _rough_usd(1000, "some-unknown-model")
    # Should use blended default ($3/MTok)
    assert "$0.003" in result


def test_rough_usd_very_small() -> None:
    result = _rough_usd(1, "claude-sonnet-4")
    # $0.000003 — should show 5 decimal places
    assert "$0.0000" in result


def test_rough_usd_medium() -> None:
    result = _rough_usd(5000, "claude-sonnet-4")
    assert "$0.015" in result


# ── _load_entry_offline ──────────────────────────────────────────────


def test_load_entry_offline_found(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")
    audit_writer.record(request_id="req_abc", model="test-model")
    entry = _load_entry_offline("req_abc")
    assert entry is not None
    assert entry["req"] == "req_abc"
    assert entry["model"] == "test-model"


def test_load_entry_offline_not_found(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")
    audit_writer.record(request_id="req_abc")
    assert _load_entry_offline("nonexistent") is None


def test_load_entry_offline_no_file(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "nonexistent" / "audit.jsonl")
    assert _load_entry_offline("anything") is None


# ── CLI command ──────────────────────────────────────────────────────


def test_explain_json_output(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")
    audit_writer.record(
        request_id="req_json",
        model="claude-sonnet-4",
        tokens_in=1000,
        tokens_out=500,
    )

    runner = CliRunner()
    result = runner.invoke(explain, ["req_json", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["req"] == "req_json"
    assert data["tokens_in"] == 1000


def test_explain_not_found(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")

    runner = CliRunner()
    result = runner.invoke(explain, ["nonexistent"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_explain_rich_output(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")
    audit_writer.record(
        request_id="req_rich",
        model="claude-sonnet-4",
        provider="anthropic",
        path="/v1/messages",
        tokens_in=4812,
        tokens_out=892,
        transforms=["SmartCrusher", "CacheAligner"],
        overhead_ms=48.3,
    )

    runner = CliRunner()
    result = runner.invoke(explain, ["req_rich"])
    assert result.exit_code == 0
    assert "req_rich" in result.output
    assert "SmartCrusher" in result.output
    assert "CacheAligner" in result.output
    assert "4,812" in result.output or "4812" in result.output


def test_explain_shows_path(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")
    audit_writer.record(
        request_id="req_path",
        path="/v1/messages",
        tokens_in=100,
        tokens_out=80,
    )

    runner = CliRunner()
    result = runner.invoke(explain, ["req_path"])
    assert result.exit_code == 0
    assert "/v1/messages" in result.output


def test_explain_inflation_warning(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")
    audit_writer.record(
        request_id="req_inflate",
        tokens_in=100,
        tokens_out=200,  # inflation!
    )

    runner = CliRunner()
    result = runner.invoke(explain, ["req_inflate"])
    assert result.exit_code == 0
    assert "nflation" in result.output.lower() or "✗" in result.output


def test_explain_cached_entry(tmp_path: Path) -> None:
    from copium.proxy import audit_writer

    audit_writer.configure(path=tmp_path / "audit.jsonl")
    audit_writer.record(
        request_id="req_cached",
        tokens_in=500,
        tokens_out=500,
        cached=True,
    )

    runner = CliRunner()
    result = runner.invoke(explain, ["req_cached"])
    assert result.exit_code == 0
    assert "cache" in result.output.lower()
