"""Strangeness tax evaluation benchmark.

Measures whether compressed output degrades LLM task accuracy compared
to uncompressed baselines. The "strangeness tax" is the accuracy penalty
from showing LLMs unfamiliar compressed formats.

Target: Copium-compressed output must achieve ≥98% of baseline accuracy.

Usage:
    pytest tests/test_evals/strangeness.py -v -s
    pytest tests/test_evals/strangeness.py -v -k "not llm"  # infra only
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from copium.compress import compress
from copium.config import CopiumConfig
from copium.tokenizers import get_tokenizer


# ── Evaluation cases ──────────────────────────────────────────────────────


@dataclass
class StrangenessEvalCase:
    """A single evaluation case for measuring strangeness tax."""

    id: str
    category: str  # git_status, git_diff, test_output, grep, build_log
    content: str  # The CLI output to compress
    questions: list[str]  # Questions an LLM should answer from the content
    expected_answers: list[str]  # Ground truth answers
    critical_markers: list[str]  # Markers that MUST survive compression


@dataclass
class StrangenessEvalResult:
    """Result for one evaluation case."""

    case_id: str
    category: str
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    markers_preserved: int
    markers_total: int
    marker_preservation_rate: float
    accuracy_on_compressed: float | None = None  # Requires LLM call
    accuracy_on_original: float | None = None  # Requires LLM call


# ── Test fixtures ─────────────────────────────────────────────────────────

GIT_STATUS_CASE = StrangenessEvalCase(
    id="git_status_mixed",
    category="git_status",
    content="""\
On branch feature/payment-gateway
Your branch is ahead of 'origin/feature/payment-gateway' by 3 commits.
  (use "git push" to publish your local commits)

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
\tmodified:   src/payments/stripe.py
\tnew file:   src/payments/paypal.py
\tdeleted:    src/payments/legacy_gateway.py

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
\tmodified:   src/main.py
\tmodified:   tests/test_payments.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
\tsrc/payments/webhook_handler.py
\tconfig/payment_providers.yaml
""",
    questions=[
        "What branch are we on?",
        "Which files are staged for commit?",
        "Are there any deleted files?",
        "What untracked files exist?",
        "How many commits ahead of origin?",
    ],
    expected_answers=[
        "feature/payment-gateway",
        "src/payments/stripe.py, src/payments/paypal.py, src/payments/legacy_gateway.py",
        "Yes, src/payments/legacy_gateway.py",
        "src/payments/webhook_handler.py, config/payment_providers.yaml",
        "3",
    ],
    critical_markers=[
        "feature/payment-gateway",
        "src/payments/stripe.py",
        "src/payments/paypal.py",
        "src/payments/legacy_gateway.py",
        "src/main.py",
        "tests/test_payments.py",
        "src/payments/webhook_handler.py",
        "config/payment_providers.yaml",
        "modified",
        "new file",
        "deleted",
    ],
)

GIT_DIFF_CASE = StrangenessEvalCase(
    id="git_diff_refactor",
    category="git_diff",
    content="""\
diff --git a/src/payments/stripe.py b/src/payments/stripe.py
index a1b2c3d..e4f5g6h 100644
--- a/src/payments/stripe.py
+++ b/src/payments/stripe.py
@@ -15,8 +15,12 @@ class StripeGateway:
     def __init__(self, api_key: str):
         self.api_key = api_key
         self.client = stripe.Client(api_key)
+        self.webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
+        self.max_retries = 3

     def charge(self, amount: int, currency: str, token: str) -> ChargeResult:
-        response = self.client.charges.create(amount=amount, currency=currency, source=token)
-        return ChargeResult(id=response.id, status=response.status)
+        for attempt in range(self.max_retries):
+            try:
+                response = self.client.charges.create(
+                    amount=amount, currency=currency, source=token
+                )
+                return ChargeResult(id=response.id, status=response.status)
+            except stripe.error.RateLimitError:
+                if attempt == self.max_retries - 1:
+                    raise
+                time.sleep(2 ** attempt)
""",
    questions=[
        "What new attributes were added to StripeGateway?",
        "What error handling was added?",
        "What was the old charge implementation?",
        "How many retries are configured?",
    ],
    expected_answers=[
        "webhook_secret and max_retries",
        "Retry logic for RateLimitError with exponential backoff",
        "Single call to client.charges.create without retry",
        "3",
    ],
    critical_markers=[
        "webhook_secret",
        "max_retries",
        "RateLimitError",
        "stripe.error",
        "amount",
        "currency",
        "source=token",
        "2 ** attempt",
    ],
)

TEST_OUTPUT_CASE = StrangenessEvalCase(
    id="pytest_failures",
    category="test_output",
    content="""\
============================= test session starts ==============================
platform linux -- Python 3.12.4, pytest-8.3.4, pluggy-1.5.0
rootdir: /home/user/payment-service
collected 89 items

tests/test_payments.py::test_stripe_charge_success PASSED            [  1%]
tests/test_payments.py::test_stripe_charge_declined PASSED           [  2%]
tests/test_payments.py::test_stripe_webhook_valid PASSED             [  3%]
tests/test_payments.py::test_paypal_create_order PASSED              [  4%]
tests/test_payments.py::test_paypal_capture PASSED                   [  5%]
tests/test_payments.py::test_refund_full PASSED                      [  6%]
tests/test_payments.py::test_refund_partial FAILED                   [  7%]
tests/test_payments.py::test_currency_conversion PASSED              [  8%]
tests/test_payments.py::test_idempotency_key PASSED                  [  9%]
tests/test_payments.py::test_rate_limit_retry FAILED                 [ 10%]

=================================== FAILURES ===================================
_____________________ test_refund_partial ______________________________________

    def test_refund_partial():
        charge = create_test_charge(amount=5000)
        result = gateway.refund(charge.id, amount=2500)
>       assert result.amount == 2500
E       AssertionError: assert 5000 == 2500
E        +  where 5000 = RefundResult(id='re_123', amount=5000, status='succeeded').amount

tests/test_payments.py:67: AssertionError
_____________________ test_rate_limit_retry ____________________________________

    def test_rate_limit_retry():
        with mock.patch.object(gateway.client.charges, 'create') as mock_create:
            mock_create.side_effect = [
                stripe.error.RateLimitError("Rate limited"),
                stripe.error.RateLimitError("Rate limited"),
                mock_charge_response(),
            ]
            result = gateway.charge(1000, "usd", "tok_123")
>       assert result.status == "succeeded"
E       stripe.error.RateLimitError: Rate limited

tests/test_payments.py:82: AssertionError
=========================== short test summary info ============================
FAILED tests/test_payments.py::test_refund_partial - assert 5000 == 2500
FAILED tests/test_payments.py::test_rate_limit_retry - stripe.error.RateLimitError
========================= 87 passed, 2 failed ================================
""",
    questions=[
        "How many tests passed and how many failed?",
        "What test failed regarding refunds?",
        "What was the expected refund amount?",
        "What error caused test_rate_limit_retry to fail?",
        "What's the root cause of the partial refund bug?",
    ],
    expected_answers=[
        "87 passed, 2 failed",
        "test_refund_partial",
        "2500",
        "stripe.error.RateLimitError",
        "Refund returned full amount (5000) instead of partial (2500)",
    ],
    critical_markers=[
        "87 passed",
        "2 failed",
        "test_refund_partial",
        "test_rate_limit_retry",
        "assert 5000 == 2500",
        "RateLimitError",
        "amount=2500",
        "tests/test_payments.py:67",
        "tests/test_payments.py:82",
    ],
)

BUILD_LOG_CASE = StrangenessEvalCase(
    id="cargo_build_errors",
    category="build_log",
    content="""\
   Compiling payment-service v0.3.2 (/home/user/payment-service)
error[E0308]: mismatched types
  --> src/payments/stripe.rs:45:16
   |
45 |     let amount: u32 = calculate_total(items);
   |                 ---   ^^^^^^^^^^^^^^^^^^^^^^ expected `u32`, found `i64`
   |                 |
   |                 expected due to this
   |
help: you can convert an `i64` to a `u32` and panic if the converted value doesn't fit
   |
45 |     let amount: u32 = calculate_total(items).try_into().unwrap();
   |                                             ++++++++++++++++++++

error[E0599]: no method named `refund_partial` found for struct `StripeClient` in the current scope
  --> src/payments/stripe.rs:78:20
   |
78 |         self.client.refund_partial(charge_id, amount)
   |                    ^^^^^^^^^^^^^^ method not found in `StripeClient`
   |
   = help: items from traits can only be used if the trait is in scope
help: the following trait is implemented but not in scope; perhaps add a `use` for it:
   |
1  + use crate::traits::Refundable;
   |

warning: unused import: `crate::legacy::Gateway`
 --> src/payments/mod.rs:3:5
  |
3 | use crate::legacy::Gateway;
  |     ^^^^^^^^^^^^^^^^^^^^^^
  |
  = note: `#[warn(unused_imports)]` on by default

error: aborting due to 2 previous errors; 1 warning emitted

For more information about an error, try `rustc --explain E0308`.
""",
    questions=[
        "How many errors and warnings are there?",
        "What type mismatch error exists?",
        "What method is missing?",
        "What's the suggested fix for the type error?",
        "What trait needs to be imported?",
    ],
    expected_answers=[
        "2 errors, 1 warning",
        "Expected u32 but found i64 at stripe.rs:45",
        "refund_partial on StripeClient",
        "Use .try_into().unwrap()",
        "crate::traits::Refundable",
    ],
    critical_markers=[
        "E0308",
        "E0599",
        "mismatched types",
        "u32",
        "i64",
        "refund_partial",
        "StripeClient",
        "Refundable",
        "stripe.rs:45",
        "stripe.rs:78",
        "try_into().unwrap()",
        "2 previous errors",
    ],
)


def get_strangeness_eval_cases() -> list[StrangenessEvalCase]:
    """Return all strangeness tax evaluation cases."""
    return [
        GIT_STATUS_CASE,
        GIT_DIFF_CASE,
        TEST_OUTPUT_CASE,
        BUILD_LOG_CASE,
    ]


# ── Infrastructure tests (no LLM calls) ──────────────────────────────────


class TestStrangenessInfrastructure:
    """Tests for strangeness evaluation infrastructure (no LLM calls)."""

    def test_cases_available(self):
        """Verify evaluation cases are available."""
        cases = get_strangeness_eval_cases()
        assert len(cases) >= 4
        assert all(isinstance(c, StrangenessEvalCase) for c in cases)

    def test_case_categories(self):
        """Verify cases cover different content types."""
        cases = get_strangeness_eval_cases()
        categories = {c.category for c in cases}
        assert "git_status" in categories
        assert "git_diff" in categories
        assert "test_output" in categories
        assert "build_log" in categories

    def test_cases_have_questions(self):
        """Verify each case has questions and expected answers."""
        for case in get_strangeness_eval_cases():
            assert len(case.questions) >= 3, f"{case.id} needs >= 3 questions"
            assert len(case.questions) == len(case.expected_answers)
            assert len(case.critical_markers) >= 5, f"{case.id} needs >= 5 markers"

    def test_critical_markers_present_in_original(self):
        """Verify critical markers actually exist in the original content."""
        for case in get_strangeness_eval_cases():
            for marker in case.critical_markers:
                assert marker in case.content, (
                    f"Marker '{marker}' not found in {case.id} content"
                )


class TestStrangenessCompression:
    """Test that Copium compression preserves critical markers."""

    @pytest.fixture
    def config(self) -> CopiumConfig:
        return CopiumConfig()

    @pytest.fixture
    def tokenizer(self):
        return get_tokenizer()

    def _compress_content(self, content: str, config: CopiumConfig) -> str:
        """Compress content through the Copium pipeline."""
        messages = [
            {"role": "user", "content": "Show me the output"},
            {"role": "assistant", "content": content},
        ]
        compressed = compress(messages, config=config)
        if compressed and len(compressed) > 1:
            return compressed[-1].get("content", content)
        return content

    def test_git_status_markers_preserved(self, config, tokenizer):
        """Critical markers in git status output survive compression."""
        case = GIT_STATUS_CASE
        compressed = self._compress_content(case.content, config)
        preserved = sum(1 for m in case.critical_markers if m in compressed)
        rate = preserved / len(case.critical_markers)
        assert rate >= 0.8, (
            f"Marker preservation {rate:.0%} below 80% threshold. "
            f"Missing: {[m for m in case.critical_markers if m not in compressed]}"
        )

    def test_git_diff_markers_preserved(self, config, tokenizer):
        """Critical markers in git diff output survive compression."""
        case = GIT_DIFF_CASE
        compressed = self._compress_content(case.content, config)
        preserved = sum(1 for m in case.critical_markers if m in compressed)
        rate = preserved / len(case.critical_markers)
        assert rate >= 0.8, (
            f"Marker preservation {rate:.0%} below 80% threshold. "
            f"Missing: {[m for m in case.critical_markers if m not in compressed]}"
        )

    def test_test_output_markers_preserved(self, config, tokenizer):
        """Critical markers in test output survive compression."""
        case = TEST_OUTPUT_CASE
        compressed = self._compress_content(case.content, config)
        preserved = sum(1 for m in case.critical_markers if m in compressed)
        rate = preserved / len(case.critical_markers)
        assert rate >= 0.8, (
            f"Marker preservation {rate:.0%} below 80% threshold. "
            f"Missing: {[m for m in case.critical_markers if m not in compressed]}"
        )

    def test_build_log_markers_preserved(self, config, tokenizer):
        """Critical markers in build log output survive compression."""
        case = BUILD_LOG_CASE
        compressed = self._compress_content(case.content, config)
        preserved = sum(1 for m in case.critical_markers if m in compressed)
        rate = preserved / len(case.critical_markers)
        assert rate >= 0.8, (
            f"Marker preservation {rate:.0%} below 80% threshold. "
            f"Missing: {[m for m in case.critical_markers if m not in compressed]}"
        )

    def test_compression_actually_saves_tokens(self, config, tokenizer):
        """Verify compression reduces token count on verbose outputs."""
        for case in get_strangeness_eval_cases():
            original_tokens = tokenizer.count(case.content)
            compressed = self._compress_content(case.content, config)
            compressed_tokens = tokenizer.count(compressed)
            # At least some savings (or content unchanged for already-terse)
            assert compressed_tokens <= original_tokens, (
                f"{case.id}: compressed ({compressed_tokens}) > original ({original_tokens})"
            )

    def test_no_strangeness_tax_threshold(self, config, tokenizer):
        """Aggregate marker preservation must be >= 85% across all cases."""
        total_markers = 0
        preserved_markers = 0

        for case in get_strangeness_eval_cases():
            compressed = self._compress_content(case.content, config)
            for marker in case.critical_markers:
                total_markers += 1
                if marker in compressed:
                    preserved_markers += 1

        rate = preserved_markers / total_markers if total_markers > 0 else 0
        assert rate >= 0.85, (
            f"Overall marker preservation {rate:.0%} below 85% threshold. "
            f"{preserved_markers}/{total_markers} markers preserved."
        )


# ── LLM-based evaluation (requires API key) ──────────────────────────────


@pytest.mark.skipif(
    not pytest.importorskip("anthropic", reason="anthropic not installed"),
    reason="anthropic SDK not installed",
)
class TestStrangenessWithLLM:
    """Tests requiring LLM calls to measure actual accuracy impact.

    Skipped unless ANTHROPIC_API_KEY is set and anthropic is installed.
    """

    @pytest.fixture(autouse=True)
    def _skip_without_key(self):
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

    def test_llm_accuracy_on_compressed_git_status(self):
        """LLM achieves ≥98% accuracy on compressed git status."""
        # Placeholder — requires LLM integration
        pytest.skip("LLM evaluation not yet wired up")

    def test_llm_accuracy_on_compressed_git_diff(self):
        """LLM achieves ≥98% accuracy on compressed git diff."""
        pytest.skip("LLM evaluation not yet wired up")

    def test_llm_accuracy_on_compressed_test_output(self):
        """LLM achieves ≥98% accuracy on compressed test output."""
        pytest.skip("LLM evaluation not yet wired up")
