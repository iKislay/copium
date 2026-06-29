"""Copium hooks package — compression hooks and compaction event hooks."""

from ..hooks import CompressContext, CompressEvent, CompressionHooks
from .compaction import (
    EntropyScorer,
    InputPriorityHooks,
    PostCompactHookData,
    PreCompactHookData,
)
from .scoring import MessageEntropyScorer, MessageScore

__all__ = [
    "CompressContext",
    "CompressEvent",
    "CompressionHooks",
    "EntropyScorer",
    "InputPriorityHooks",
    "MessageEntropyScorer",
    "MessageScore",
    "PostCompactHookData",
    "PreCompactHookData",
]
