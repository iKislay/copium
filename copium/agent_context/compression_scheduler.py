"""Compression scheduler for agent context management.

Decides WHEN and HOW MUCH to compress based on the current agent phase,
context pressure, and content type. Maps phases to transform pipelines
from Copium's existing 37+ transform modules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from copium.agent_context.phase_detector import AgentPhase
from copium.agent_context.smart_zone import CompressionLevel
from copium.agent_context.tool_call_classifier import ClassifiedToolCall, ToolCallType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransformSpec:
    """Specification for a single transform in a pipeline."""

    name: str
    aggressiveness: float = 0.5  # 0.0 = gentle, 1.0 = maximum compression
    preserve_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompressionPlan:
    """Complete compression plan for a tool call result."""

    transforms: list[TransformSpec]
    target_reduction: float  # Target token reduction ratio
    phase: AgentPhase
    compression_level: CompressionLevel
    content_type: ToolCallType
    priority: int  # Higher = more urgent to compress


# Phase → pipeline mapping with per-transform aggressiveness
PHASE_PIPELINES: dict[AgentPhase, list[TransformSpec]] = {
    AgentPhase.ORIENTATION: [
        TransformSpec("smart_crusher", aggressiveness=0.90, preserve_fields=()),
        TransformSpec("session_dedup", aggressiveness=0.80),
        TransformSpec(
            "differential_response", aggressiveness=0.85, preserve_fields=("file_path",)
        ),
    ],
    AgentPhase.EXPLORATION: [
        TransformSpec(
            "content_router", aggressiveness=0.60, preserve_fields=("file_path",)
        ),
        TransformSpec("session_dedup", aggressiveness=0.70),
        TransformSpec(
            "error_compressor",
            aggressiveness=0.65,
            preserve_fields=("error_type", "message"),
        ),
        TransformSpec("toon_encoder", aggressiveness=0.40),
    ],
    AgentPhase.IMPLEMENTATION: [
        TransformSpec("session_dedup", aggressiveness=0.50),
        TransformSpec(
            "error_compressor",
            aggressiveness=0.60,
            preserve_fields=("error_type", "message", "file_path"),
        ),
        TransformSpec("schema_compressor", aggressiveness=0.55),
    ],
    AgentPhase.VERIFICATION: [
        TransformSpec(
            "differential_response",
            aggressiveness=0.85,
            preserve_fields=("pass_fail_count",),
        ),
        TransformSpec("smart_crusher", aggressiveness=0.80),
        TransformSpec(
            "error_compressor",
            aggressiveness=0.70,
            preserve_fields=("error_type",),
        ),
    ],
    AgentPhase.UNKNOWN: [
        TransformSpec("session_dedup", aggressiveness=0.50),
        TransformSpec("smart_crusher", aggressiveness=0.50),
    ],
}

# Content-type specific compression routes
CONTENT_TYPE_ROUTES: dict[ToolCallType, TransformSpec] = {
    ToolCallType.DIRECTORY_LISTING: TransformSpec(
        "smart_crusher", aggressiveness=0.95
    ),
    ToolCallType.GREP_SEARCH: TransformSpec(
        "smart_crusher", aggressiveness=0.90, preserve_fields=("file_path", "line_number")
    ),
    ToolCallType.FILE_READ: TransformSpec(
        "session_dedup", aggressiveness=0.0, preserve_fields=("file_path", "content")
    ),
    ToolCallType.ERROR_OUTPUT: TransformSpec(
        "error_compressor",
        aggressiveness=0.70,
        preserve_fields=("error_type", "message"),
    ),
    ToolCallType.TEST_RUN: TransformSpec(
        "differential_response",
        aggressiveness=0.85,
        preserve_fields=("pass_fail_count",),
    ),
    ToolCallType.JSON_DATA: TransformSpec("toon_encoder", aggressiveness=0.40),
    ToolCallType.GIT_OPERATION: TransformSpec(
        "smart_crusher",
        aggressiveness=0.80,
        preserve_fields=("file_path", "change_type"),
    ),
    ToolCallType.CONFIG_READ: TransformSpec(
        "session_dedup", aggressiveness=0.0
    ),
    ToolCallType.SCHEMA_DEFINITION: TransformSpec(
        "schema_compressor", aggressiveness=0.57
    ),
    ToolCallType.DOCUMENTATION: TransformSpec(
        "output_compressor", aggressiveness=0.30
    ),
}


class CompressionScheduler:
    """Decides WHEN and HOW MUCH to compress, selecting transform pipelines.

    Combines phase-based pipelines with content-type-specific routes
    to produce an optimal compression plan for each tool call result.

    Example:
        >>> scheduler = CompressionScheduler()
        >>> plan = scheduler.schedule(
        ...     phase=AgentPhase.ORIENTATION,
        ...     compression_level=CompressionLevel.LOSSLESS,
        ...     classified=classified_tool_call,
        ...     context_pressure=0.3,
        ... )
        >>> plan.transforms[0].name
        'smart_crusher'
    """

    def __init__(
        self,
        phase_pipelines: dict[AgentPhase, list[TransformSpec]] | None = None,
        content_routes: dict[ToolCallType, TransformSpec] | None = None,
    ):
        """Initialize scheduler with optional custom pipelines.

        Args:
            phase_pipelines: Override default phase → pipeline mapping.
            content_routes: Override default content type → transform routes.
        """
        self._phase_pipelines = phase_pipelines or PHASE_PIPELINES
        self._content_routes = content_routes or CONTENT_TYPE_ROUTES

    def schedule(
        self,
        phase: AgentPhase,
        compression_level: CompressionLevel,
        classified: ClassifiedToolCall,
        context_pressure: float = 0.0,
    ) -> CompressionPlan:
        """Create a compression plan for a tool call result.

        Args:
            phase: Current agent phase.
            compression_level: Required compression intensity.
            classified: Classified tool call with type metadata.
            context_pressure: Current context usage as fraction of Smart Zone.

        Returns:
            CompressionPlan with ordered transforms and target reduction.
        """
        # Get base pipeline for current phase
        base_transforms = list(self._phase_pipelines.get(phase, []))

        # Get content-type-specific transform
        content_transform = self._content_routes.get(classified.tool_type)

        # Merge: content-specific transform takes priority, then phase pipeline
        transforms = self._merge_transforms(base_transforms, content_transform)

        # Adjust aggressiveness based on compression level
        transforms = self._adjust_aggressiveness(transforms, compression_level)

        if compression_level == CompressionLevel.AGGRESSIVE_LOSSY:
            if not any(t.name == "output_compressor" for t in transforms):
                transforms.append(TransformSpec("output_compressor", aggressiveness=1.0))

        # Calculate target reduction
        target_reduction = self._calculate_target(
            compression_level, classified, context_pressure
        )

        # Calculate priority (higher = compress sooner)
        priority = self._calculate_priority(classified, context_pressure)

        return CompressionPlan(
            transforms=transforms,
            target_reduction=target_reduction,
            phase=phase,
            compression_level=compression_level,
            content_type=classified.tool_type,
            priority=priority,
        )

    def schedule_batch(
        self,
        phase: AgentPhase,
        compression_level: CompressionLevel,
        classified_calls: list[ClassifiedToolCall],
        context_pressure: float = 0.0,
    ) -> list[CompressionPlan]:
        """Schedule compression for multiple tool calls, sorted by priority.

        Returns plans sorted by priority (highest first), so the most
        compressible/least valuable content is compressed first.
        """
        plans = [
            self.schedule(phase, compression_level, c, context_pressure)
            for c in classified_calls
        ]
        return sorted(plans, key=lambda p: p.priority, reverse=True)

    def _merge_transforms(
        self,
        base: list[TransformSpec],
        content_specific: TransformSpec | None,
    ) -> list[TransformSpec]:
        """Merge content-specific transform into base pipeline."""
        if content_specific is None:
            return base

        # If content-specific transform is already in base, replace with
        # the content-specific version (which has tuned aggressiveness)
        result = []
        found = False
        for t in base:
            if t.name == content_specific.name:
                result.append(content_specific)
                found = True
            else:
                result.append(t)

        # If not found in base, prepend (content-specific runs first)
        if not found:
            result.insert(0, content_specific)

        return result

    def _adjust_aggressiveness(
        self,
        transforms: list[TransformSpec],
        level: CompressionLevel,
    ) -> list[TransformSpec]:
        """Scale transform aggressiveness based on compression level."""
        level_multipliers = {
            CompressionLevel.NONE: 0.0,
            CompressionLevel.LOSSLESS: 0.6,
            CompressionLevel.LIGHT_LOSSY: 0.8,
            CompressionLevel.MODERATE_LOSSY: 1.0,
            CompressionLevel.AGGRESSIVE_LOSSY: 1.2,
        }
        multiplier = level_multipliers.get(level, 1.0)

        adjusted = []
        for t in transforms:
            new_aggressiveness = min(1.0, t.aggressiveness * multiplier)
            adjusted.append(
                TransformSpec(
                    name=t.name,
                    aggressiveness=new_aggressiveness,
                    preserve_fields=t.preserve_fields,
                )
            )
        return adjusted

    def _calculate_target(
        self,
        level: CompressionLevel,
        classified: ClassifiedToolCall,
        context_pressure: float,
    ) -> float:
        """Calculate target token reduction ratio."""
        base_targets = {
            CompressionLevel.NONE: 0.0,
            CompressionLevel.LOSSLESS: 0.20,
            CompressionLevel.LIGHT_LOSSY: 0.40,
            CompressionLevel.MODERATE_LOSSY: 0.60,
            CompressionLevel.AGGRESSIVE_LOSSY: 0.80,
        }
        base = base_targets.get(level, 0.0)

        # Scale by compressibility — don't try to compress incompressible content
        scaled = base * classified.compressibility

        # Under high pressure, push harder (but respect compressibility ceiling)
        if context_pressure > 0.8:
            scaled = min(classified.compressibility, scaled * 1.3)

        return min(0.95, scaled)

    def _calculate_priority(
        self,
        classified: ClassifiedToolCall,
        context_pressure: float,
    ) -> int:
        """Calculate compression priority (0-100, higher = compress first)."""
        # Base priority from compression_priority metric (0.0-1.0)
        base = classified.compression_priority * 60

        # Boost priority under high context pressure
        pressure_bonus = context_pressure * 30

        # Low-value content gets compressed first
        value_penalty = classified.value_score * 10

        return int(base + pressure_bonus - value_penalty)
