"""Tests for compaction detector module."""

from __future__ import annotations

import time

import pytest

from copium.proxy.compaction_detector import (
    CompactionDetector,
    CompactionEvent,
    DetectorConfig,
)


class TestCompactionDetector:
    """Tests for CompactionDetector."""

    def test_no_trigger_below_threshold(self):
        detector = CompactionDetector()
        # 50K tokens out of 200K = 25% — well below 83.5%
        event = detector.check("session-1", "claude-opus-4", 50_000)
        assert event is None

    def test_trigger_at_threshold(self):
        detector = CompactionDetector()
        # 170K tokens out of 200K = 85% — above 83.5%
        event = detector.check("session-1", "claude-opus-4", 170_000)
        assert event is not None
        assert isinstance(event, CompactionEvent)
        assert event.session_id == "session-1"
        assert event.model == "claude-opus-4"
        assert event.token_usage == 170_000
        assert event.context_window == 200_000
        assert event.usage_pct == pytest.approx(0.85, abs=0.01)

    def test_no_trigger_when_disabled(self):
        config = DetectorConfig(enabled=False)
        detector = CompactionDetector(config)
        event = detector.check("session-1", "claude-opus-4", 170_000)
        assert event is None

    def test_cooldown_prevents_repeat_events(self):
        config = DetectorConfig(cooldown_seconds=60.0)
        detector = CompactionDetector(config)

        # First trigger works
        event1 = detector.check("session-1", "claude-opus-4", 170_000)
        assert event1 is not None

        # Second trigger within cooldown is suppressed
        event2 = detector.check("session-1", "claude-opus-4", 175_000)
        assert event2 is None

    def test_different_sessions_not_affected_by_cooldown(self):
        detector = CompactionDetector()
        event1 = detector.check("session-1", "claude-opus-4", 170_000)
        event2 = detector.check("session-2", "claude-opus-4", 170_000)
        assert event1 is not None
        assert event2 is not None

    def test_custom_threshold(self):
        config = DetectorConfig(threshold_override=0.50)
        detector = CompactionDetector(config)
        # 60% usage should trigger with 50% threshold
        event = detector.check("session-1", "claude-opus-4", 120_000)
        assert event is not None

    def test_min_tokens_requirement(self):
        config = DetectorConfig(min_tokens_for_trigger=100_000)
        detector = CompactionDetector(config)
        # 90% but only 90K tokens — below min
        event = detector.check("session-1", "gpt-4o", 90_000)
        assert event is None

    def test_context_window_detection(self):
        detector = CompactionDetector()
        assert detector.get_context_window("claude-opus-4") == 200_000
        assert detector.get_context_window("gpt-4o") == 128_000
        assert detector.get_context_window("gemini-2.5-pro") == 1_000_000
        # Unknown model defaults to 200K
        assert detector.get_context_window("unknown-model") == 200_000

    def test_reset_session(self):
        detector = CompactionDetector()
        event1 = detector.check("session-1", "claude-opus-4", 170_000)
        assert event1 is not None

        # Reset session allows re-triggering
        detector.reset_session("session-1")
        event2 = detector.check("session-1", "claude-opus-4", 170_000)
        assert event2 is not None

    def test_tokens_remaining(self):
        detector = CompactionDetector()
        event = detector.check("session-1", "claude-opus-4", 170_000)
        assert event is not None
        assert event.tokens_remaining == 30_000

    def test_stats(self):
        detector = CompactionDetector()
        detector.check("session-1", "claude-opus-4", 170_000)
        stats = detector.stats()
        assert stats["total_events"] == 1
        assert stats["active_sessions"] == 1
        assert stats["enabled"] is True

    def test_events_list(self):
        config = DetectorConfig(cooldown_seconds=0)
        detector = CompactionDetector(config)
        detector.check("s1", "claude-opus-4", 170_000)
        detector.check("s2", "claude-opus-4", 180_000)
        assert len(detector.events) == 2
