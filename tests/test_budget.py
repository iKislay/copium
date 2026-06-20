"""Tests for ContextBudgetManager."""

from __future__ import annotations

import pytest

from copium.budget import (
    BudgetAllocation,
    BudgetCheck,
    BudgetZone,
    ContextBudgetManager,
    ModelCapabilities,
    _estimate_tokens_from_messages,
    _normalize_model_name,
)
from copium.config import ContextBudgetConfig


@pytest.fixture
def budget():
    """ContextBudgetManager with default config."""
    return ContextBudgetManager(ContextBudgetConfig())


@pytest.fixture
def budget_strict():
    """ContextBudgetManager with strict thresholds."""
    return ContextBudgetManager(
        ContextBudgetConfig(warning_threshold=0.50, danger_threshold=0.70)
    )


class TestNormalizeModelName:
    def test_strip_provider_prefix(self):
        assert _normalize_model_name("openai/gpt-4o") == "gpt-4o"
        assert _normalize_model_name("anthropic/claude-3-5-sonnet") == "claude-3-5-sonnet"
        assert _normalize_model_name("ollama/qwen2.5-coder:32b") == "qwen2.5-coder:32b"

    def test_strip_suffixes(self):
        assert _normalize_model_name("qwen2.5-coder-32b-chat") == "qwen2.5-coder-32b"
        assert _normalize_model_name("llama3.1-8b-instruct-gguf") == "llama3.1-8b"

    def test_lowercase(self):
        assert _normalize_model_name("GPT-4o") == "gpt-4o"


class TestTokenEstimation:
    def test_basic_text(self):
        text = "Hello world, this is a test."
        est = _estimate_tokens_from_messages([{"role": "user", "content": text}])
        # ~29 chars / 4 = ~7 tokens + 4 overhead
        assert 5 <= est <= 15

    def test_list_content(self):
        messages = [
            {
                "role": "tool",
                "content": [
                    {"type": "text", "text": "File contents here"},
                    {"type": "text", "text": "More content"},
                ],
            }
        ]
        est = _estimate_tokens_from_messages(messages)
        assert est > 0

    def test_empty_messages(self):
        est = _estimate_tokens_from_messages([])
        assert est == 0


class TestModelCapabilities:
    def test_known_model(self, budget):
        caps = budget.detect_model("gpt-4o")
        assert caps.max_context == 128_000
        assert caps.kv_cache_type == "unknown"

    def test_unknown_model_defaults(self, budget):
        caps = budget.detect_model("some-random-model")
        assert caps.max_context == 32_768  # Conservative default

    def test_override_max_context(self, budget):
        caps = budget.detect_model("gpt-4o", max_context=8192)
        assert caps.max_context == 8192

    def test_kv_cache_type(self, budget):
        caps = budget.detect_model("gpt-4o", kv_cache_type="q4_0")
        assert caps.kv_cache_type == "q4_0"
        # Q4_0 at 25% reliable fraction: 128K * 0.25 = 32K
        assert caps.reliable_context == 32_000

    def test_reliable_context_fp16(self, budget):
        caps = budget.detect_model("gpt-4o", kv_cache_type="f16")
        assert caps.reliable_context == int(128_000 * 0.95)

    def test_reliable_context_q8_0(self, budget):
        caps = budget.detect_model("gpt-4o", kv_cache_type="q8_0")
        assert caps.reliable_context == int(128_000 * 0.50)

    def test_model_override(self):
        budget = ContextBudgetManager(
            ContextBudgetConfig(model_overrides={"my-model": 16384})
        )
        caps = budget.detect_model("my-model")
        assert caps.max_context == 16384

    def test_caching(self, budget):
        caps1 = budget.detect_model("gpt-4o")
        caps2 = budget.detect_model("gpt-4o")
        assert caps1 is caps2  # Same object from cache


class TestBudgetCheck:
    def test_safe_zone(self, budget):
        caps = budget.detect_model("gpt-4o")
        messages = [{"role": "user", "content": "Hello"}]
        check = budget.check_budget(messages, caps)
        assert check.zone == BudgetZone.SAFE
        assert check.fits

    def test_warning_zone(self, budget_strict):
        caps = budget_strict.detect_model("gpt-4o", max_context=20000)
        # 20K context, 50% reliable = 10K reliable, 50% warning = 5K tokens
        big_content = "x" * 30_000  # ~7.5K tokens - should trigger warning
        messages = [{"role": "tool", "content": big_content}]
        check = budget_strict.check_budget(messages, caps)
        assert check.zone in (BudgetZone.WARNING, BudgetZone.DANGER, BudgetZone.OVER)

    def test_danger_zone(self, budget_strict):
        caps = budget_strict.detect_model("gpt-4o", max_context=20000)
        # 20K context, 50% reliable = 10K reliable, 70% danger = 7K tokens
        huge_content = "x" * 50_000  # ~12.5K tokens - should trigger danger
        messages = [{"role": "tool", "content": huge_content}]
        check = budget_strict.check_budget(messages, caps)
        assert check.zone in (BudgetZone.DANGER, BudgetZone.OVER)

    def test_over_zone(self, budget):
        caps = budget.detect_model("gpt-4o", max_context=1000)
        huge_content = "x" * 20_000  # Way over 1K context
        messages = [{"role": "tool", "content": huge_content}]
        check = budget.check_budget(messages, caps)
        assert check.zone == BudgetZone.OVER
        assert not check.fits

    def test_output_reservation(self, budget):
        caps = budget.detect_model("gpt-4o")
        messages = []
        check = budget.check_budget(messages, caps)
        # Should reserve 15% of reliable context for output
        expected_output = min(4096, int(caps.reliable_context * 0.15))
        assert check.reserved_output == expected_output

    def test_suggestion_none_in_safe(self, budget):
        caps = budget.detect_model("gpt-4o")
        messages = [{"role": "user", "content": "Hello"}]
        check = budget.check_budget(messages, caps)
        assert check.suggestion == "none"

    def test_suggestion_in_danger(self, budget):
        caps = budget.detect_model("gpt-4o", max_context=2000)
        huge_content = "x" * 30_000
        messages = [{"role": "tool", "content": huge_content}]
        check = budget.check_budget(messages, caps)
        assert check.suggestion != "none"


class TestBudgetAllocation:
    def test_basic_allocation(self, budget):
        caps = budget.detect_model("gpt-4o")
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        alloc = budget.allocate(messages, caps)
        assert alloc.total_context == 128_000
        assert alloc.system_prompt_tokens > 0
        assert alloc.available_for_tools > 0
        assert alloc.utilization_pct < 10

    def test_no_system_prompt(self, budget):
        caps = budget.detect_model("gpt-4o")
        messages = [{"role": "user", "content": "Hello"}]
        alloc = budget.allocate(messages, caps)
        assert alloc.system_prompt_tokens == 0


class TestCompressionProfile:
    def test_safe_gives_moderate(self, budget):
        check = BudgetCheck(
            estimated_tokens=100,
            total_budget=128_000,
            reserved_output=4096,
            available_for_input=123_904,
            usage_pct=0.1,
            zone=BudgetZone.SAFE,
            suggestion="none",
        )
        assert budget.suggest_compression_profile(check) == "moderate"

    def test_warning_gives_aggressive(self, budget):
        check = BudgetCheck(
            estimated_tokens=100_000,
            total_budget=128_000,
            reserved_output=4096,
            available_for_input=123_904,
            usage_pct=80.7,
            zone=BudgetZone.WARNING,
            suggestion="compress",
        )
        assert budget.suggest_compression_profile(check) == "aggressive"


class TestFormatReport:
    def test_report_contains_key_info(self, budget):
        caps = budget.detect_model("gpt-4o")
        messages = [{"role": "user", "content": "Hello"}]
        check = budget.check_budget(messages, caps)
        report = budget.format_report(check)
        assert "Context Budget Report" in report
        assert "gpt-4o" in report
        assert "tokens" in report
