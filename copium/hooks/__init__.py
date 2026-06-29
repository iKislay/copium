"""Copium hooks package — compression hooks and compaction event hooks."""

from ..hooks import CompressContext, CompressEvent, CompressionHooks
from .compaction import (
    EntropyScorer,
    InputPriorityHooks,
    PostCompactHookData,
    PreCompactHookData,
)

__all__ = [
    "CompressContext",
    "CompressEvent",
    "CompressionHooks",
    "EntropyScorer",
    "InputPriorityHooks",
    "PostCompactHookData",
    "PreCompactHookData",
]
