"""Strands Agents integration for Copium SDK.

This module provides seamless integration with Strands Agents,
enabling automatic context optimization for Strands agents.

Components:
1. CopiumStrandsModel - Wraps any Strands model to apply Copium transforms
2. CopiumHookProvider - Hook provider for Strands agents
3. get_copium_provider - Detects appropriate provider for a Strands model
4. get_model_name_from_strands - Extracts model name from a Strands model

Example:
    from strands import Agent
    from strands.models import BedrockModel
    from copium.integrations.strands import CopiumStrandsModel

    # Wrap any Strands model
    model = BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0")
    optimized_model = CopiumStrandsModel(model)

    # Use with agent
    agent = Agent(model=optimized_model)
    response = agent("Hello!")
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .bundle import CopiumBundle
    from .hooks import CopiumHookProvider
    from .model import CopiumStrandsModel, OptimizationMetrics, optimize_messages
    from .providers import get_copium_provider, get_model_name_from_strands


def strands_available() -> bool:
    """Check if strands-agents is installed and available.

    Returns:
        True if strands-agents package is available, False otherwise.
    """
    return importlib.util.find_spec("strands") is not None


# Lazy imports to avoid import errors when strands is not installed
def __getattr__(name: str) -> Any:
    """Lazy import of integration components."""
    if name == "CopiumHookProvider":
        from .hooks import CopiumHookProvider

        return CopiumHookProvider
    elif name == "CopiumStrandsModel":
        from .model import CopiumStrandsModel

        return CopiumStrandsModel
    elif name == "OptimizationMetrics":
        from .model import OptimizationMetrics

        return OptimizationMetrics
    elif name == "optimize_messages":
        from .model import optimize_messages

        return optimize_messages
    elif name == "get_copium_provider":
        from .providers import get_copium_provider

        return get_copium_provider
    elif name == "get_model_name_from_strands":
        from .providers import get_model_name_from_strands

        return get_model_name_from_strands
    elif name == "CopiumBundle":
        from .bundle import CopiumBundle

        return CopiumBundle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Availability check
    "strands_available",
    # Hook provider
    "CopiumHookProvider",
    # Model wrapper
    "CopiumStrandsModel",
    "OptimizationMetrics",
    "optimize_messages",
    # Provider detection
    "get_copium_provider",
    "get_model_name_from_strands",
    # One-helper MCP + hook wiring (Copium + Serena + RTK-equivalent)
    "CopiumBundle",
]
