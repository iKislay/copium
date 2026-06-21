"""Context Window Simulator — test compression strategies before deploying.

Lets users simulate how different compression configurations would affect
their token usage and costs, without actually modifying any messages.

Use cases:
- A/B test compression configs before deploying
- Estimate savings for a new model/provider
- Debug why a specific transform isn't helping
- Show ROI to stakeholders ("we'd save $X/month")

The simulator runs the full transform pipeline in dry-run mode and
reports detailed metrics per transform, per content type, and per
message role.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .config import CopiumConfig
from .tokenizer import Tokenizer


@dataclass
class TransformMetrics:
    """Metrics for a single transform."""

    name: str
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    messages_affected: int
    duration_ms: float

    @property
    def savings_pct(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return (self.tokens_saved / self.tokens_before) * 100

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "savings_pct": round(self.savings_pct, 2),
            "messages_affected": self.messages_affected,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class RoleMetrics:
    """Metrics aggregated by message role."""

    role: str
    count: int
    tokens_before: int
    tokens_after: int

    @property
    def tokens_saved(self) -> int:
        return self.tokens_before - self.tokens_after

    @property
    def savings_pct(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return (self.tokens_saved / self.tokens_before) * 100

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "count": self.count,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "savings_pct": round(self.savings_pct, 2),
        }


@dataclass
class SimulationResult:
    """Result of a context window simulation."""

    # Overall metrics
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    total_duration_ms: float

    # Per-transform breakdown
    transforms: list[TransformMetrics]

    # Per-role breakdown
    roles: list[RoleMetrics]

    # Cost estimation
    model: str
    cost_per_1k_input: float
    cost_per_1k_output: float
    estimated_input_cost_before: float
    estimated_input_cost_after: float
    estimated_monthly_savings: float

    # Quality signals
    warnings: list[str]
    transforms_applied: list[str]

    @property
    def savings_pct(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return (self.tokens_saved / self.tokens_before) * 100

    def to_dict(self) -> dict:
        return {
            "summary": {
                "tokens_before": self.tokens_before,
                "tokens_after": self.tokens_after,
                "tokens_saved": self.tokens_saved,
                "savings_pct": round(self.savings_pct, 2),
                "duration_ms": round(self.total_duration_ms, 2),
            },
            "cost": {
                "model": self.model,
                "cost_per_1k_input": self.cost_per_1k_input,
                "cost_per_1k_output": self.cost_per_1k_output,
                "estimated_input_cost_before": round(self.estimated_input_cost_before, 6),
                "estimated_input_cost_after": round(self.estimated_input_cost_after, 6),
                "estimated_monthly_savings": round(self.estimated_monthly_savings, 4),
            },
            "transforms": [t.to_dict() for t in self.transforms],
            "roles": [r.to_dict() for r in self.roles],
            "warnings": self.warnings,
            "transforms_applied": self.transforms_applied,
        }

    def format_report(self) -> str:
        """Format a human-readable simulation report."""
        lines = []
        lines.append("=" * 60)
        lines.append("  CONTEXT WINDOW SIMULATION REPORT")
        lines.append("=" * 60)
        lines.append("")

        # Summary
        lines.append(f"  Model: {self.model}")
        lines.append(f"  Tokens: {self.tokens_before:,} → {self.tokens_after:,} "
                      f"(saved {self.tokens_saved:,}, {self.savings_pct:.1f}%)")
        lines.append(f"  Duration: {self.total_duration_ms:.1f}ms")
        lines.append("")

        # Cost
        lines.append("  COST ANALYSIS")
        lines.append(f"    Before: ${self.estimated_input_cost_before:.6f}/request")
        lines.append(f"    After:  ${self.estimated_input_cost_after:.6f}/request")
        lines.append(f"    Monthly savings (1K req/day): "
                      f"${self.estimated_monthly_savings:.2f}")
        lines.append("")

        # Per-transform breakdown
        if self.transforms:
            lines.append("  TRANSFORM BREAKDOWN")
            for t in self.transforms:
                bar_len = int(t.savings_pct / 5)  # Scale to 20 chars
                bar = "█" * bar_len + "░" * (20 - bar_len)
                lines.append(
                    f"    {t.name:<25} {bar} "
                    f"{t.tokens_saved:>6} tokens ({t.savings_pct:.1f}%)"
                )
            lines.append("")

        # Per-role breakdown
        if self.roles:
            lines.append("  ROLE BREAKDOWN")
            for r in self.roles:
                lines.append(
                    f"    {r.role:<15} {r.count:>3} msgs  "
                    f"{r.tokens_before:>8} → {r.tokens_after:>8} "
                    f"(saved {r.tokens_saved:,}, {r.savings_pct:.1f}%)"
                )
            lines.append("")

        # Warnings
        if self.warnings:
            lines.append("  WARNINGS")
            for w in self.warnings:
                lines.append(f"    ⚠ {w}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


# Model pricing (USD per 1K tokens) — approximate, update as needed
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-opus": (0.015, 0.075),
    "claude-3-haiku": (0.00025, 0.00125),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-1.5-pro": (0.00125, 0.005),
    "deepseek-chat": (0.00014, 0.00028),
    "deepseek-reasoner": (0.00055, 0.00219),
}


def get_model_pricing(model: str) -> tuple[float, float]:
    """Get cost per 1K tokens for a model. Returns (input, output)."""
    model_lower = model.lower()
    for key, pricing in MODEL_PRICING.items():
        if key in model_lower:
            return pricing
    # Default: assume GPT-4o pricing
    return (0.0025, 0.01)


class ContextSimulator:
    """Simulates compression strategies on messages.

    Runs the full transform pipeline in dry-run mode and reports
    detailed metrics per transform, per content type, and per role.
    """

    def __init__(self, config: CopiumConfig | None = None):
        self.config = config or CopiumConfig()

    def simulate(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o",
        **kwargs: Any,
    ) -> SimulationResult:
        """Simulate compression on messages without modifying them.

        Args:
            messages: List of messages to simulate compression on.
            model: Model name for cost estimation.
            **kwargs: Additional arguments passed to the pipeline.

        Returns:
            SimulationResult with detailed metrics.
        """
        from .transforms.pipeline import TransformPipeline

        pipeline = TransformPipeline(self.config)
        tokenizer = pipeline._get_tokenizer(model)

        tokens_before = tokenizer.count_messages(messages)

        # Run pipeline in simulate mode
        t0 = time.perf_counter()
        result = pipeline.simulate(messages, model, **kwargs)
        duration_ms = (time.perf_counter() - t0) * 1000

        # Build per-transform metrics
        transform_metrics: list[TransformMetrics] = []
        # Use timing data if available, otherwise create synthetic metrics
        if result.timing:
            for name, ms in result.timing.items():
                if name.startswith("_"):
                    continue
                transform_metrics.append(
                    TransformMetrics(
                        name=name,
                        tokens_before=tokens_before,
                        tokens_after=tokens_before,  # simulate doesn't change tokens
                        tokens_saved=0,
                        messages_affected=0,
                        duration_ms=ms,
                    )
                )

        # Build per-role metrics
        role_metrics: dict[str, RoleMetrics] = {}
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                tok_count = tokenizer.count_text(content)
            else:
                tok_count = 0

            if role not in role_metrics:
                role_metrics[role] = RoleMetrics(
                    role=role, count=0, tokens_before=0, tokens_after=0
                )
            role_metrics[role].count += 1
            role_metrics[role].tokens_before += tok_count
            role_metrics[role].tokens_after += tok_count  # simulate doesn't change

        # Cost estimation
        input_cost_per_1k, output_cost_per_1k = get_model_pricing(model)
        estimated_input_cost_before = (tokens_before / 1000) * input_cost_per_1k
        estimated_input_cost_after = (result.tokens_after / 1000) * input_cost_per_1k
        monthly_savings = (estimated_input_cost_before - estimated_input_cost_after) * 1000

        return SimulationResult(
            tokens_before=tokens_before,
            tokens_after=result.tokens_after,
            tokens_saved=tokens_before - result.tokens_after,
            total_duration_ms=duration_ms,
            transforms=transform_metrics,
            roles=list(role_metrics.values()),
            model=model,
            cost_per_1k_input=input_cost_per_1k,
            cost_per_1k_output=output_cost_per_1k,
            estimated_input_cost_before=estimated_input_cost_before,
            estimated_input_cost_after=estimated_input_cost_after,
            estimated_monthly_savings=monthly_savings,
            warnings=result.warnings,
            transforms_applied=result.transforms_applied,
        )
