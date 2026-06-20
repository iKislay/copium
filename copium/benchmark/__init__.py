"""A/B Benchmarking Framework.

Run two compression configs side-by-side, measure cost AND quality
on the same prompts. Essential for proving value.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copium.config import CopiumConfig


@dataclass
class BenchmarkPrompt:
    """A prompt for benchmarking."""

    id: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    expected_output: str | None = None  # For quality evaluation
    tags: list[str] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    """Result of running a single config on a prompt."""

    config_name: str
    prompt_id: str

    # Token metrics
    tokens_before: int = 0
    tokens_after: int = 0
    tokens_saved: int = 0
    savings_percent: float = 0.0

    # Cost metrics
    cost_before: float = 0.0
    cost_after: float = 0.0
    cost_saved: float = 0.0

    # Quality metrics (if expected_output provided)
    quality_score: float | None = None  # 0-1 similarity score
    response_length: int = 0

    # Timing
    latency_ms: float = 0.0

    # Metadata
    transforms_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ABTestConfig:
    """Configuration for an A/B test."""

    name: str
    description: str = ""

    # Config A (baseline)
    config_a_name: str = "baseline"
    config_a: CopiumConfig = field(default_factory=CopiumConfig)

    # Config B (treatment)
    config_b_name: str = "treatment"
    config_b: CopiumConfig = field(default_factory=CopiumConfig)

    # Prompts to test
    prompts: list[BenchmarkPrompt] = field(default_factory=list)

    # Evaluation settings
    evaluate_quality: bool = False
    quality_threshold: float = 0.8  # Minimum quality score to accept


@dataclass
class ABTestResult:
    """Result of an A/B test."""

    test_name: str
    config_a_name: str
    config_b_name: str

    # Aggregate metrics
    config_a_results: list[BenchmarkResult] = field(default_factory=list)
    config_b_results: list[BenchmarkResult] = field(default_factory=list)

    # Summary
    total_tokens_saved: int = 0
    total_cost_saved: float = 0.0
    avg_savings_percent: float = 0.0
    winner: str = ""  # "config_a" or "config_b"

    # Quality comparison
    quality_degradation: float = 0.0  # Negative = B is better


class ABenchmarker:
    """A/B benchmarking framework for comparing compression configs."""

    def __init__(self) -> None:
        self._results: list[ABTestResult] = []

    def create_test(
        self,
        name: str,
        config_a: CopiumConfig,
        config_b: CopiumConfig,
        prompts: list[BenchmarkPrompt],
        **kwargs: Any,
    ) -> ABTestConfig:
        """Create a new A/B test configuration."""
        return ABTestConfig(
            name=name,
            config_a=config_a,
            config_b=config_b,
            prompts=prompts,
            **kwargs,
        )

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate token count from messages."""
        return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    def _estimate_cost(self, tokens: int, model: str = "gpt-4o") -> float:
        """Estimate cost from tokens."""
        pricing = {
            "gpt-4o": 0.0025 / 1000,
            "gpt-4o-mini": 0.00015 / 1000,
            "claude-sonnet-4-20250514": 0.003 / 1000,
        }
        return tokens * pricing.get(model, 0.002 / 1000)

    def _run_config(
        self,
        config_name: str,
        config: CopiumConfig,
        prompt: BenchmarkPrompt,
    ) -> BenchmarkResult:
        """Run a single config on a prompt."""
        from copium.transforms.pipeline import TransformPipeline
        from copium.tokenizer import Tokenizer
        from copium.tokenizers.estimator import EstimatingTokenCounter

        tokenizer = Tokenizer(EstimatingTokenCounter())
        pipeline = TransformPipeline(config)

        tokens_before = self._estimate_tokens(prompt.messages)

        start_time = time.time()
        result = pipeline.apply(prompt.messages, tokenizer)
        latency_ms = (time.time() - start_time) * 1000

        tokens_after = self._estimate_tokens(result.messages)
        cost_before = self._estimate_cost(tokens_before)
        cost_after = self._estimate_cost(tokens_after)

        return BenchmarkResult(
            config_name=config_name,
            prompt_id=prompt.id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_before - tokens_after,
            savings_percent=((tokens_before - tokens_after) / tokens_before * 100) if tokens_before > 0 else 0,
            cost_before=cost_before,
            cost_after=cost_after,
            cost_saved=cost_before - cost_after,
            latency_ms=latency_ms,
            transforms_applied=result.transforms_applied,
            warnings=result.warnings,
        )

    def run_test(self, test_config: ABTestConfig) -> ABTestResult:
        """Run an A/B test and return results."""
        result = ABTestResult(
            test_name=test_config.name,
            config_a_name=test_config.config_a_name,
            config_b_name=test_config.config_b_name,
        )

        for prompt in test_config.prompts:
            # Run config A
            a_result = self._run_config(
                test_config.config_a_name,
                test_config.config_a,
                prompt,
            )
            result.config_a_results.append(a_result)

            # Run config B
            b_result = self._run_config(
                test_config.config_b_name,
                test_config.config_b,
                prompt,
            )
            result.config_b_results.append(b_result)

        # Calculate aggregates
        total_a_tokens = sum(r.tokens_after for r in result.config_a_results)
        total_b_tokens = sum(r.tokens_after for r in result.config_b_results)

        result.total_tokens_saved = sum(r.tokens_saved for r in result.config_b_results)
        result.total_cost_saved = sum(r.cost_saved for r in result.config_b_results)

        avg_a_savings = sum(r.savings_percent for r in result.config_a_results) / len(result.config_a_results) if result.config_a_results else 0
        avg_b_savings = sum(r.savings_percent for r in result.config_b_results) / len(result.config_b_results) if result.config_b_results else 0

        result.avg_savings_percent = avg_b_savings

        # Determine winner
        if total_b_tokens < total_a_tokens:
            result.winner = test_config.config_b_name
        else:
            result.winner = test_config.config_a_name

        self._results.append(result)
        return result

    def export_results(self, result: ABTestResult, path: Path) -> None:
        """Export results to JSON."""
        data = {
            "test_name": result.test_name,
            "config_a": result.config_a_name,
            "config_b": result.config_b_name,
            "winner": result.winner,
            "total_tokens_saved": result.total_tokens_saved,
            "total_cost_saved": result.total_cost_saved,
            "avg_savings_percent": result.avg_savings_percent,
            "config_a_results": [
                {
                    "prompt_id": r.prompt_id,
                    "tokens_before": r.tokens_before,
                    "tokens_after": r.tokens_after,
                    "savings_percent": r.savings_percent,
                    "latency_ms": r.latency_ms,
                }
                for r in result.config_a_results
            ],
            "config_b_results": [
                {
                    "prompt_id": r.prompt_id,
                    "tokens_before": r.tokens_before,
                    "tokens_after": r.tokens_after,
                    "savings_percent": r.savings_percent,
                    "latency_ms": r.latency_ms,
                }
                for r in result.config_b_results
            ],
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)
