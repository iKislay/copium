"""Agno integration for Copium SDK.

This module provides seamless integration with Agno (formerly Phidata),
enabling automatic context optimization for Agno agents.

Components:
1. CopiumAgnoModel - Wraps any Agno model to apply Copium transforms
2. create_copium_hooks - Creates pre/post hooks for Agno agents
3. optimize_messages - Standalone function for manual optimization

Example:
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from copium.integrations.agno import CopiumAgnoModel

    # Wrap any Agno model
    model = OpenAIChat(id="gpt-4o")
    optimized_model = CopiumAgnoModel(model)

    # Use with agent
    agent = Agent(model=optimized_model)
    response = agent.run("Hello!")
"""

from .hooks import (
    CopiumPostHook,
    CopiumPreHook,
    HookMetrics,
    create_copium_hooks,
)
from .model import (
    CopiumAgnoModel,
    OptimizationMetrics,
    agno_available,
    optimize_messages,
)
from .providers import get_copium_provider, get_model_name_from_agno

__all__ = [
    # Model wrapper
    "CopiumAgnoModel",
    "OptimizationMetrics",
    "agno_available",
    "optimize_messages",
    # Hooks
    "create_copium_hooks",
    "CopiumPreHook",
    "CopiumPostHook",
    "HookMetrics",
    # Provider detection
    "get_copium_provider",
    "get_model_name_from_agno",
]
