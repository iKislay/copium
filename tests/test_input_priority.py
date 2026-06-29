"""Tests for input-priority compression hooks and entropy scoring."""

from __future__ import annotations

import pytest

from copium.hooks.compaction import (
    EntropyScorer,
    InputPriorityHooks,
    PostCompactHookData,
    PreCompactHookData,
)
from copium.hooks.scoring import MessageEntropyScorer, MessageScore
from copium.hooks import CompressContext


class TestPreCompactHookData:
    """Tests for PreCompactHookData dataclass."""

    def test_basic_creation(self):
        data = PreCompactHookData(
            context_tokens_before=180_000,
            context_tokens_after_estimate=60_000,
            messages_count=142,
            tool_calls_count=87,
            compaction_reason="context_limit",
            messages=[{"role": "user", "content": "test"}],
            compressed_content={"abc123": "file contents..."},
        )
        assert data.context_tokens_before == 180_000
        assert data.messages_count == 142
        assert data.compaction_reason == "context_limit"

    def test_compression_ratio_estimate(self):
        data = PreCompactHookData(
            context_tokens_before=200_000,
            context_tokens_after_estimate=50_000,
            messages_count=100,
            tool_calls_count=50,
            compaction_reason="context_limit",
            messages=[],
            compressed_content={},
        )
        assert data.compression_ratio_estimate == 0.25

    def test_compression_ratio_zero_tokens(self):
        data = PreCompactHookData(
            context_tokens_before=0,
            context_tokens_after_estimate=0,
            messages_count=0,
            tool_calls_count=0,
            compaction_reason="manual",
            messages=[],
            compressed_content={},
        )
        assert data.compression_ratio_estimate == 0.0


class TestPostCompactHookData:
    """Tests for PostCompactHookData dataclass."""

    def test_basic_creation(self):
        data = PostCompactHookData(
            context_tokens_after=50_000,
            messages_kept=[{"role": "user", "content": "test"}],
            messages_compressed=["hash1", "hash2"],
            ccr_references=["ccr_ref_1", "ccr_ref_2"],
            session_id="session-123",
            model="claude-opus-4",
            compression_ratio=0.25,
            tokens_saved=150_000,
        )
        assert data.context_tokens_after == 50_000
        assert len(data.messages_compressed) == 2
        assert len(data.ccr_references) == 2
        assert data.tokens_saved == 150_000


class TestEntropyScorer:
    """Tests for EntropyScorer."""

    def test_empty_text(self):
        scorer = EntropyScorer()
        assert scorer.score("") == 0.0

    def test_short_text(self):
        scorer = EntropyScorer(ngram_size=3)
        assert scorer.score("ab") == 0.0  # Shorter than ngram_size

    def test_repetitive_text(self):
        scorer = EntropyScorer()
        # Very repetitive → low entropy
        score = scorer.score("aaa" * 100)
        assert score < 0.3

    def test_diverse_text(self):
        scorer = EntropyScorer()
        # Diverse content → higher entropy
        text = "The quick brown fox jumps over the lazy dog. " * 5
        score = scorer.score(text)
        assert score > 0.3

    def test_random_text_high_entropy(self):
        scorer = EntropyScorer()
        import string
        import random

        random.seed(42)
        text = "".join(random.choices(string.ascii_letters + string.digits, k=500))
        score = scorer.score(text)
        assert score > 0.5

    def test_score_message(self):
        scorer = EntropyScorer()
        msg = {"role": "user", "content": "Fix the authentication bug in src/auth.ts"}
        score = scorer.score_message(msg)
        assert 0.0 <= score <= 1.0

    def test_score_message_multipart(self):
        scorer = EntropyScorer()
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyze this code"},
                {"type": "text", "text": "def hello(): pass"},
            ],
        }
        score = scorer.score_message(msg)
        assert 0.0 <= score <= 1.0


class TestInputPriorityHooks:
    """Tests for InputPriorityHooks."""

    def test_user_messages_get_low_bias(self):
        hooks = InputPriorityHooks(use_entropy_scoring=False)
        messages = [
            {"role": "user", "content": "Fix the bug"},
            {"role": "assistant", "content": "I'll fix it"},
            {"role": "tool", "content": "file contents " * 100},
        ]
        ctx = CompressContext(model="claude-sonnet-4")
        biases = hooks.compute_biases(messages, ctx)

        assert biases[0] == 0.3  # User — preserve
        assert biases[1] == 1.0  # Assistant — normal
        assert biases[2] == 1.5  # Tool — compress more

    def test_entropy_scoring_adjusts_biases(self):
        hooks = InputPriorityHooks(use_entropy_scoring=True)
        messages = [
            {"role": "user", "content": "Implement the WebSocket handler with proper reconnection and heartbeat mechanism"},
            {"role": "tool", "content": "line 1\n" * 200},  # Very repetitive
        ]
        ctx = CompressContext(model="claude-sonnet-4")
        biases = hooks.compute_biases(messages, ctx)

        # User should be preserved more (lower bias)
        # Tool output is repetitive, should be compressed more
        assert biases[0] < biases[1]

    def test_pre_compress_passthrough(self):
        hooks = InputPriorityHooks()
        messages = [{"role": "user", "content": "test"}]
        ctx = CompressContext()
        result = hooks.pre_compress(messages, ctx)
        assert result is messages  # No modification

    def test_custom_bias_values(self):
        hooks = InputPriorityHooks(
            user_bias=0.1,
            assistant_bias=0.8,
            tool_bias=2.0,
            use_entropy_scoring=False,
        )
        messages = [
            {"role": "user", "content": "query"},
            {"role": "assistant", "content": "response"},
            {"role": "tool", "content": "output"},
        ]
        ctx = CompressContext()
        biases = hooks.compute_biases(messages, ctx)

        assert biases[0] == 0.1
        assert biases[1] == 0.8
        assert biases[2] == 2.0


class TestMessageEntropyScorer:
    """Tests for MessageEntropyScorer."""

    def test_score_messages_basic(self):
        scorer = MessageEntropyScorer()
        messages = [
            {"role": "user", "content": "Fix the authentication bug in src/auth/middleware.ts"},
            {"role": "assistant", "content": "I'll fix the authentication middleware."},
            {"role": "tool", "content": "export function auth() {}\n" * 50},
        ]
        scores = scorer.score_messages(messages)

        assert len(scores) == 3
        assert all(isinstance(s, MessageScore) for s in scores)

    def test_user_messages_have_higher_priority(self):
        scorer = MessageEntropyScorer()
        messages = [
            {"role": "user", "content": "Implement WebSocket reconnection with exponential backoff"},
            {"role": "tool", "content": "line 1\nline 2\nline 3\n" * 100},
        ]
        scores = scorer.score_messages(messages)

        # User message should have higher preservation priority
        assert scores[0].preservation_priority > scores[1].preservation_priority

    def test_compute_biases_returns_dict(self):
        scorer = MessageEntropyScorer()
        messages = [
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": "response"},
        ]
        biases = scorer.compute_biases(messages)

        assert isinstance(biases, dict)
        assert 0 in biases
        assert 1 in biases
        assert all(0.0 < v < 3.0 for v in biases.values())

    def test_tool_outputs_more_compressible(self):
        scorer = MessageEntropyScorer()
        messages = [
            {"role": "user", "content": "What's in auth.ts?"},
            {"role": "tool", "content": "export function validate() {\n  return true;\n}\n" * 30},
        ]
        scores = scorer.score_messages(messages)

        assert scores[1].compressibility > scores[0].compressibility

    def test_empty_message(self):
        scorer = MessageEntropyScorer()
        messages = [{"role": "user", "content": ""}]
        scores = scorer.score_messages(messages)
        assert scores[0].entropy == 0.0

    def test_preservation_priority_range(self):
        scorer = MessageEntropyScorer()
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Fix the bug"},
            {"role": "assistant", "content": "Sure, I'll fix it"},
            {"role": "tool", "content": "output data " * 50},
        ]
        scores = scorer.score_messages(messages)

        for score in scores:
            assert 0.0 <= score.preservation_priority <= 1.0
            assert 0.0 < score.compression_bias <= 2.0
