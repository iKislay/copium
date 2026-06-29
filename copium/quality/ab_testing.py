"""A/B testing framework for compression quality validation.

Enables controlled experiments comparing compressed vs uncompressed
context across real agent workloads with statistical rigor.

Test types:
- Automated accuracy tests (ground truth comparison)
- Shadow production tests (compression without affecting responses)
- Quality regression detection
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class ABTestConfig:
    """Configuration for A/B testing."""

    enabled: bool = False
    sample_rate: float = 0.05
    compressor: str = "auto"
    quality_threshold: float = 0.98
    min_samples: int = 2400
    auto_promote: bool = False
    auto_rollback: bool = False


@dataclass
class ABTestResult:
    """Result of an A/B test analysis."""

    test_id: str
    group_a_accuracy: float
    group_b_accuracy: float
    delta: float
    delta_pct: float
    p_value: float
    effect_size: float
    ci_95: tuple
    n_per_group: int
    significant: bool
    recommendation: str


@dataclass
class _TestState:
    """Internal state for a running test."""

    test_id: str
    results_a: List[dict] = field(default_factory=list)
    results_b: List[dict] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    compressor_name: str = ""


class ABTestHarness:
    """A/B testing harness for compression quality validation.

    Tracks parallel experiments comparing compressed vs uncompressed
    context quality with proper statistical analysis.

    Example:
        harness = ABTestHarness(ABTestConfig(enabled=True))
        harness.start_test("crusher_v2")
        harness.record_result("crusher_v2", "a", accuracy=0.95, tokens=12000)
        harness.record_result("crusher_v2", "b", accuracy=0.94, tokens=2100)
        status = harness.get_status("crusher_v2")
    """

    def __init__(self, config: Optional[ABTestConfig] = None):
        self.config = config or ABTestConfig()
        self._tests: Dict[str, _TestState] = {}

    def start_test(self, test_id: str, compressor_name: str = "") -> None:
        """Start a new A/B test."""
        self._tests[test_id] = _TestState(
            test_id=test_id,
            compressor_name=compressor_name,
            start_time=time.time(),
        )

    def record_result(
        self,
        test_id: str,
        group: str,
        accuracy: float,
        tokens: int = 0,
        cost: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a single result for a test group.

        Args:
            test_id: Test identifier.
            group: "a" (control) or "b" (treatment/compressed).
            accuracy: Task accuracy score (0.0-1.0).
            tokens: Number of tokens used.
            cost: API cost in dollars.
            latency_ms: Response latency in milliseconds.
        """
        state = self._tests.get(test_id)
        if not state:
            return

        entry = {
            "accuracy": accuracy,
            "tokens": tokens,
            "cost": cost,
            "latency_ms": latency_ms,
            "timestamp": time.time(),
        }

        if group == "a":
            state.results_a.append(entry)
        elif group == "b":
            state.results_b.append(entry)

    def should_sample(self) -> bool:
        """Determine if this request should be sampled for A/B testing."""
        if not self.config.enabled:
            return False
        return random.random() < self.config.sample_rate

    def get_status(self, test_id: str) -> Optional[ABTestResult]:
        """Get current status and analysis of a running test."""
        state = self._tests.get(test_id)
        if not state:
            return None

        n_a = len(state.results_a)
        n_b = len(state.results_b)

        if n_a < 2 or n_b < 2:
            return ABTestResult(
                test_id=test_id,
                group_a_accuracy=0.0,
                group_b_accuracy=0.0,
                delta=0.0,
                delta_pct=0.0,
                p_value=1.0,
                effect_size=0.0,
                ci_95=(0.0, 0.0),
                n_per_group=max(n_a, n_b),
                significant=False,
                recommendation="CONTINUE: Insufficient data.",
            )

        acc_a = [r["accuracy"] for r in state.results_a]
        acc_b = [r["accuracy"] for r in state.results_b]

        mean_a = sum(acc_a) / n_a
        mean_b = sum(acc_b) / n_b
        delta = mean_b - mean_a
        delta_pct = (delta / max(0.001, mean_a)) * 100

        # Variance
        var_a = sum((x - mean_a) ** 2 for x in acc_a) / max(1, n_a - 1)
        var_b = sum((x - mean_b) ** 2 for x in acc_b) / max(1, n_b - 1)

        # Welch's t-test approximation
        se = math.sqrt(var_a / n_a + var_b / n_b) if (var_a + var_b) > 0 else 0.001
        t_stat = delta / se if se > 0 else 0.0

        # Approximate p-value using normal distribution for large samples
        p_value = 2 * (1 - self._normal_cdf(abs(t_stat)))

        # Cohen's d effect size
        pooled_std = math.sqrt((var_a + var_b) / 2) if (var_a + var_b) > 0 else 0.001
        cohens_d = delta / pooled_std

        # 95% confidence interval
        ci_low = delta - 1.96 * se
        ci_high = delta + 1.96 * se

        significant = p_value < 0.05
        quality_ok = mean_b >= mean_a * self.config.quality_threshold

        if significant and quality_ok:
            recommendation = "DEPLOY: Compression maintains quality with token savings."
        elif significant and not quality_ok:
            recommendation = "HOLD: Quality degradation detected. Review compressor settings."
        else:
            recommendation = "CONTINUE: Not enough data for significant conclusion."

        return ABTestResult(
            test_id=test_id,
            group_a_accuracy=mean_a,
            group_b_accuracy=mean_b,
            delta=delta,
            delta_pct=delta_pct,
            p_value=p_value,
            effect_size=cohens_d,
            ci_95=(ci_low, ci_high),
            n_per_group=max(n_a, n_b),
            significant=significant,
            recommendation=recommendation,
        )

    def list_tests(self) -> List[str]:
        """List all active test IDs."""
        return list(self._tests.keys())

    def stop_test(self, test_id: str) -> Optional[ABTestResult]:
        """Stop a test and return final results."""
        result = self.get_status(test_id)
        self._tests.pop(test_id, None)
        return result

    @staticmethod
    def calculate_sample_size(
        baseline_accuracy: float = 0.95,
        minimum_detectable_effect: float = 0.02,
        alpha: float = 0.05,
        power: float = 0.80,
    ) -> int:
        """Calculate required sample size for detecting an effect.

        Args:
            baseline_accuracy: Expected accuracy without compression.
            minimum_detectable_effect: Smallest effect worth detecting.
            alpha: Significance level (Type I error rate).
            power: Statistical power (1 - Type II error rate).

        Returns:
            Required samples per group.
        """
        p1 = baseline_accuracy
        p2 = baseline_accuracy * (1 - minimum_detectable_effect)
        p_avg = (p1 + p2) / 2

        z_alpha = ABTestHarness._normal_ppf(1 - alpha / 2)
        z_beta = ABTestHarness._normal_ppf(power)

        numerator = (
            z_alpha * math.sqrt(2 * p_avg * (1 - p_avg))
            + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
        )
        denominator = abs(p1 - p2)

        if denominator == 0:
            return 10000

        n = (numerator / denominator) ** 2
        return int(math.ceil(n))

    @staticmethod
    def _normal_cdf(x: float) -> float:
        """Approximate standard normal CDF."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    @staticmethod
    def _normal_ppf(p: float) -> float:
        """Approximate standard normal inverse CDF (percent point function)."""
        # Rational approximation for 0 < p < 1
        if p <= 0:
            return -4.0
        if p >= 1:
            return 4.0
        if p == 0.5:
            return 0.0

        if p < 0.5:
            t = math.sqrt(-2 * math.log(p))
        else:
            t = math.sqrt(-2 * math.log(1 - p))

        # Abramowitz and Stegun approximation
        c0 = 2.515517
        c1 = 0.802853
        c2 = 0.010328
        d1 = 1.432788
        d2 = 0.189269
        d3 = 0.001308

        result = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)

        if p < 0.5:
            return -result
        return result
