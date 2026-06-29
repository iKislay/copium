"""Smart Zone budget calculator and enforcer.

The Smart Zone is the portion of the context window an agent can use
while maintaining peak reasoning quality. Beyond it, model performance
degrades non-linearly (the 40% threshold).

Factors:
- Model family (Claude, GPT-4, Gemini, local quantized)
- Task type (exploration, implementation, debugging, review)
- Quantization level (FP16, Q8_0, Q4_0 for local models)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CompressionLevel(Enum):
    """Compression aggressiveness levels."""

    NONE = "none"
    LOSSLESS = "lossless"
    LIGHT_LOSSY = "light_lossy"
    MODERATE_LOSSY = "moderate_lossy"
    AGGRESSIVE_LOSSY = "aggressive_lossy"


# Quality factors per quantization/deployment type
QUALITY_FACTORS: dict[str, float] = {
    "fp16": 0.40,
    "q8_0": 0.30,
    "q4_0": 0.20,
    "cloud": 0.40,
}

# Task factors — how much of the Smart Zone each task type uses
TASK_FACTORS: dict[str, float] = {
    "exploration": 0.80,
    "implementation": 1.00,
    "debugging": 0.90,
    "review": 1.10,
}

# Model scaling factors
MODEL_FACTORS: dict[str, float] = {
    "claude-4": 1.00,
    "claude-3.5": 1.00,
    "claude-3": 0.95,
    "gpt-4o": 0.95,
    "gpt-4": 0.90,
    "gemini-2": 1.05,
    "gemini-1.5": 1.00,
    "local-7b": 0.70,
    "local-13b": 0.85,
    "local-70b": 0.95,
}


@dataclass(frozen=True)
class SmartZoneConfig:
    """Configuration for Smart Zone calculation."""

    context_window: int = 200_000
    model_family: str = "claude-4"
    quantization: str = "cloud"
    task_type: str = "implementation"

    def __post_init__(self) -> None:
        if self.context_window <= 0:
            raise ValueError("context_window must be positive")


@dataclass(frozen=True)
class SmartZoneBudget:
    """Calculated Smart Zone budget with per-phase allocations."""

    total_tokens: int
    smart_zone_tokens: int
    orientation_budget: int  # 10% of Smart Zone
    exploration_budget: int  # 20% of Smart Zone
    implementation_budget: int  # 25% of Smart Zone
    verification_budget: int  # 10% of Smart Zone
    reserved_for_reasoning: int  # 35% of Smart Zone

    @property
    def smart_zone_pct(self) -> float:
        """Smart Zone as percentage of total context."""
        if self.total_tokens == 0:
            return 0.0
        return (self.smart_zone_tokens / self.total_tokens) * 100

    @property
    def tool_output_budget(self) -> int:
        """Total budget available for tool outputs (65% of Smart Zone)."""
        return (
            self.orientation_budget
            + self.exploration_budget
            + self.implementation_budget
            + self.verification_budget
        )


class SmartZone:
    """Calculates and enforces Smart Zone budget.

    The Smart Zone represents the portion of context window that can be
    used while maintaining peak model performance. Exceeding it causes
    non-linear quality degradation.

    Example:
        >>> zone = SmartZone(SmartZoneConfig(context_window=200000))
        >>> budget = zone.calculate_budget()
        >>> budget.smart_zone_tokens
        80000
        >>> zone.should_compress(current_usage=70000, incoming_tokens=15000)
        True
    """

    def __init__(self, config: SmartZoneConfig):
        self._config = config
        self._budget = self._calculate()

    @property
    def config(self) -> SmartZoneConfig:
        return self._config

    @property
    def budget(self) -> SmartZoneBudget:
        return self._budget

    def calculate_budget(self) -> SmartZoneBudget:
        """Return the calculated Smart Zone budget."""
        return self._budget

    def remaining_budget(self, current_usage: int) -> int:
        """How many tokens remain before exiting the Smart Zone.

        Args:
            current_usage: Current token count in context.

        Returns:
            Remaining tokens before Smart Zone boundary. Can be negative
            if already past the boundary.
        """
        return self._budget.smart_zone_tokens - current_usage

    def usage_fraction(self, current_usage: int) -> float:
        """Current usage as fraction of Smart Zone (not total context).

        Args:
            current_usage: Current token count in context.

        Returns:
            Fraction of Smart Zone used (0.0 to 1.0+).
        """
        if self._budget.smart_zone_tokens == 0:
            return 1.0
        return current_usage / self._budget.smart_zone_tokens

    def should_compress(self, current_usage: int, incoming_tokens: int) -> bool:
        """Check if adding tokens would push past Smart Zone boundary.

        Args:
            current_usage: Current token count in context.
            incoming_tokens: Number of tokens about to be added.

        Returns:
            True if compression should be applied before adding.
        """
        return (current_usage + incoming_tokens) > self._budget.smart_zone_tokens

    def compression_aggressiveness(self, current_usage: int) -> CompressionLevel:
        """Determine compression intensity based on Smart Zone pressure.

        Args:
            current_usage: Current token count in context.

        Returns:
            CompressionLevel indicating how aggressively to compress.
        """
        fraction = self.usage_fraction(current_usage)

        if fraction < 0.75:
            return CompressionLevel.LOSSLESS
        elif fraction < 0.85:
            return CompressionLevel.LIGHT_LOSSY
        elif fraction < 1.0:
            return CompressionLevel.MODERATE_LOSSY
        else:
            return CompressionLevel.AGGRESSIVE_LOSSY

    def _calculate(self) -> SmartZoneBudget:
        """Calculate Smart Zone budget from config."""
        quality_factor = QUALITY_FACTORS.get(
            self._config.quantization, 0.40
        )
        task_factor = TASK_FACTORS.get(
            self._config.task_type, 1.0
        )
        model_factor = MODEL_FACTORS.get(
            self._config.model_family, 1.0
        )

        smart_zone_tokens = int(
            self._config.context_window * quality_factor * task_factor * model_factor
        )

        # Per-phase allocations (of Smart Zone, not total context)
        orientation_budget = int(smart_zone_tokens * 0.10)
        exploration_budget = int(smart_zone_tokens * 0.20)
        implementation_budget = int(smart_zone_tokens * 0.25)
        verification_budget = int(smart_zone_tokens * 0.10)
        reserved_for_reasoning = int(smart_zone_tokens * 0.35)

        return SmartZoneBudget(
            total_tokens=self._config.context_window,
            smart_zone_tokens=smart_zone_tokens,
            orientation_budget=orientation_budget,
            exploration_budget=exploration_budget,
            implementation_budget=implementation_budget,
            verification_budget=verification_budget,
            reserved_for_reasoning=reserved_for_reasoning,
        )
