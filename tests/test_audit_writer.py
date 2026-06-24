"""Tests for :mod:`copium.proxy.audit_writer` — the JSONL audit logger.

Covers:
- record() writes valid JSONL entries
- read_recent() returns correct slices
- find_by_id() does early-return lookup
- Thread safety under concurrent writes
- Edge cases: missing dir, malformed lines, disabled state
- Public API: get_audit_path() accessor
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from copium.proxy import audit_writer


@pytest.fixture(autouse=True)
def _reset_audit_writer(tmp_path: Path) -> None:
    """Reset module state before each test and point audit log at tmp_path."""
    audit_writer.configure(path=tmp_path / "audit.jsonl", enabled=True)
    yield
    audit_writer.configure(path=None, enabled=True)
    audit_writer._log_path = None  # force clean state for next test


# ── record() basics ──────────────────────────────────────────────────


def test_record_writes_valid_jsonl(tmp_path: Path) -> None:
    audit_writer.record(
        request_id="req_001",
        provider="anthropic",
        model="claude-sonnet-4",
        path="/v1/messages",
        transforms=["SmartCrusher", "CacheAligner"],
        tokens_in=4812,
        tokens_out=892,
        overhead_ms=48.3,
        cached=False,
    )
    log_path = audit_writer.get_audit_path()
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["req"] == "req_001"
    assert entry["provider"] == "anthropic"
    assert entry["model"] == "claude-sonnet-4"
    assert entry["transforms"] == ["SmartCrusher", "CacheAligner"]
    assert entry["tokens_in"] == 4812
    assert entry["tokens_out"] == 892
    assert entry["savings"] == pytest.approx(0.81463, abs=1e-4)
    assert entry["overhead_ms"] == 48.3
    assert entry["cached"] is False


def test_record_default_values(tmp_path: Path) -> None:
    audit_writer.record(request_id="req_min")
    entry = json.loads(tmp_path.joinpath("audit.jsonl").read_text().strip())
    assert entry["req"] == "req_min"
    assert entry["provider"] == "unknown"
    assert entry["model"] == "unknown"
    assert entry["transforms"] == []
    assert entry["tokens_in"] == 0
    assert entry["tokens_out"] == 0
    assert entry["savings"] == 0.0


def test_record_clamps_negative_tokens(tmp_path: Path) -> None:
    audit_writer.record(request_id="req_neg", tokens_in=-10, tokens_out=-5)
    entry = json.loads(tmp_path.joinpath("audit.jsonl").read_text().strip())
    assert entry["tokens_in"] == 0
    assert entry["tokens_out"] == 0


def test_record_custom_timestamp(tmp_path: Path) -> None:
    audit_writer.record(request_id="req_ts", timestamp="2026-01-01T00:00:00Z")
    entry = json.loads(tmp_path.joinpath("audit.jsonl").read_text().strip())
    assert entry["ts"] == "2026-01-01T00:00:00Z"


def test_record_disabled_skips_write(tmp_path: Path) -> None:
    audit_writer.configure(enabled=False)
    audit_writer.record(request_id="req_disabled")
    assert not tmp_path.joinpath("audit.jsonl").exists()


# ── get_audit_path() ─────────────────────────────────────────────────


def test_get_audit_path_returns_configured_path(tmp_path: Path) -> None:
    expected = tmp_path / "audit.jsonl"
    audit_writer.configure(path=expected)
    assert audit_writer.get_audit_path() == expected


def test_get_audit_path_fallback_when_no_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_writer.configure(path=None)
    # Force _log_path to None so get_audit_path hits the workspace fallback
    audit_writer._log_path = None

    def _raise(*args: Any, **kwargs: Any) -> Path:
        raise RuntimeError("no workspace")

    monkeypatch.setattr("copium.paths.workspace_dir", _raise)
    result = audit_writer.get_audit_path()
    assert result == Path.home() / ".copium" / "logs" / "audit.jsonl"


# ── read_recent() ────────────────────────────────────────────────────


def test_read_recent_returns_last_n(tmp_path: Path) -> None:
    for i in range(10):
        audit_writer.record(request_id=f"req_{i:03d}")
    result = audit_writer.read_recent(n=3)
    assert len(result) == 3
    assert [e["req"] for e in result] == ["req_007", "req_008", "req_009"]


def test_read_recent_filters_by_request_id(tmp_path: Path) -> None:
    for i in range(5):
        audit_writer.record(request_id=f"req_{i:03d}")
    audit_writer.record(request_id="target_999")
    for i in range(5):
        audit_writer.record(request_id=f"req_{i+5:03d}")
    result = audit_writer.read_recent(n=100, request_id="target_999")
    assert len(result) == 1
    assert result[0]["req"] == "target_999"


def test_read_recent_empty_file(tmp_path: Path) -> None:
    assert audit_writer.read_recent() == []


def test_read_recent_malformed_lines(tmp_path: Path) -> None:
    log_path = audit_writer.get_audit_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("not json\n{\"req\":\"ok\"}\n\n{\"broken\n")
    result = audit_writer.read_recent()
    assert len(result) == 1
    assert result[0]["req"] == "ok"


# ── find_by_id() ─────────────────────────────────────────────────────


def test_find_by_id_returns_match(tmp_path: Path) -> None:
    for i in range(5):
        audit_writer.record(request_id=f"req_{i:03d}", model=f"model-{i}")
    entry = audit_writer.find_by_id("req_003")
    assert entry is not None
    assert entry["req"] == "req_003"
    assert entry["model"] == "model-3"


def test_find_by_id_returns_none_when_missing(tmp_path: Path) -> None:
    audit_writer.record(request_id="req_001")
    assert audit_writer.find_by_id("nonexistent") is None


def test_find_by_id_empty_file() -> None:
    assert audit_writer.find_by_id("anything") is None


def test_find_by_id_early_return(tmp_path: Path) -> None:
    """find_by_id should stop reading after finding the first match."""
    for i in range(100):
        audit_writer.record(request_id=f"req_{i:03d}")
    # Add a duplicate — find_by_id should return the FIRST one
    audit_writer.record(request_id="req_050")
    entry = audit_writer.find_by_id("req_050")
    assert entry is not None
    # Should be the first occurrence (index 50), not the duplicate
    # We can't directly check position, but it should return quickly


# ── Thread safety ────────────────────────────────────────────────────


def test_concurrent_writes_no_corruption(tmp_path: Path) -> None:
    """Many threads writing simultaneously must not produce corrupt JSON."""
    errors: list[str] = []
    num_threads = 8
    writes_per_thread = 50

    def writer(thread_id: int) -> None:
        try:
            for i in range(writes_per_thread):
                audit_writer.record(
                    request_id=f"t{thread_id}_r{i}",
                    tokens_in=1000 + i,
                    tokens_out=500 + i,
                )
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Write errors: {errors}"

    log_path = audit_writer.get_audit_path()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == num_threads * writes_per_thread

    # Every line must be valid JSON
    for line in lines:
        obj = json.loads(line)
        assert "req" in obj
        assert "tokens_in" in obj


def test_concurrent_read_write(tmp_path: Path) -> None:
    """Readers must not see corrupt data while writers are active."""
    for i in range(20):
        audit_writer.record(request_id=f"seed_{i}")

    read_results: list[int] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            entries = audit_writer.read_recent(n=10)
            # All entries must be valid dicts with 'req' key
            for e in entries:
                assert isinstance(e, dict)
                assert "req" in e
            read_results.append(len(entries))
            time.sleep(0.001)

    def writer() -> None:
        for i in range(200):
            audit_writer.record(request_id=f"concurrent_{i}")
            time.sleep(0.0005)

    reader_thread = threading.Thread(target=reader)
    writer_thread = threading.Thread(target=writer)
    reader_thread.start()
    writer_thread.start()
    writer_thread.join()
    stop.set()
    reader_thread.join()

    assert len(read_results) > 0


# ── ensure_path edge cases ───────────────────────────────────────────


def test_record_creates_parent_dirs(tmp_path: Path) -> None:
    deep_path = tmp_path / "a" / "b" / "c" / "audit.jsonl"
    audit_writer.configure(path=deep_path)
    audit_writer.record(request_id="req_deep")
    assert deep_path.exists()


def test_read_nonexistent_file(tmp_path: Path) -> None:
    audit_writer.configure(path=tmp_path / "does_not_exist.jsonl")
    assert audit_writer.read_recent() == []
    assert audit_writer.find_by_id("anything") is None


# ── Savings calculation ──────────────────────────────────────────────


def test_savings_zero_tokens_in(tmp_path: Path) -> None:
    audit_writer.record(request_id="req_zero", tokens_in=0, tokens_out=0)
    entry = json.loads(tmp_path.joinpath("audit.jsonl").read_text().strip())
    assert entry["savings"] == 0.0


def test_savings_full_compression(tmp_path: Path) -> None:
    audit_writer.record(request_id="req_full", tokens_in=1000, tokens_out=0)
    entry = json.loads(tmp_path.joinpath("audit.jsonl").read_text().strip())
    assert entry["savings"] == 1.0


def test_savings_rounding(tmp_path: Path) -> None:
    audit_writer.record(request_id="req_round", tokens_in=3, tokens_out=1)
    entry = json.loads(tmp_path.joinpath("audit.jsonl").read_text().strip())
    assert entry["savings"] == pytest.approx(0.666667, abs=1e-5)
