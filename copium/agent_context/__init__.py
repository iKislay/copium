"""Agent-aware context management for AI coding agents.

Implements the Smart Zone framework to keep agent context usage below
the 40% quality threshold, with phase-aware compression that adapts
to the agent's lifecycle (orientation → exploration → implementation → verification).

Key components:
- PhaseDetector: Classifies agent session phase from tool call patterns
- SmartZone: Calculates and enforces context budget per phase
- ToolCallClassifier: Classifies tool calls by type and compressibility
- ContextLifecycleManager: Orchestrates the full context lifecycle
- CompressionScheduler: Selects transforms per phase and context pressure
- OrientationCache: Pre-built codebase maps to skip orientation tax
- ContextHealthMonitor: Real-time context quality metrics
"""

from copium.agent_context.phase_detector import AgentPhase, PhaseDetector
from copium.agent_context.smart_zone import SmartZone, SmartZoneConfig, SmartZoneBudget
from copium.agent_context.tool_call_classifier import (
    ToolCallClassifier,
    ToolCallType,
    ClassifiedToolCall,
)
from copium.agent_context.context_lifecycle import ContextLifecycleManager
from copium.agent_context.compression_scheduler import CompressionScheduler
from copium.agent_context.orientation_cache import OrientationCache, CodebaseMap
from copium.agent_context.context_health import ContextHealthMonitor

__all__ = [
    "AgentPhase",
    "ClassifiedToolCall",
    "CodebaseMap",
    "CompressionScheduler",
    "ContextHealthMonitor",
    "ContextLifecycleManager",
    "OrientationCache",
    "PhaseDetector",
    "SmartZone",
    "SmartZoneBudget",
    "SmartZoneConfig",
    "ToolCallClassifier",
    "ToolCallType",
]
