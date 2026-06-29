"""Copium hooks package — compression hooks and compaction event hooks.

Provides:
- Base compression hooks (CompressionHooks, CompressContext, CompressEvent)
- Pre/post compaction data models (PreCompactHookData, PostCompactHookData)
- Input-priority compression with entropy scoring (InputPriorityHooks)
- Message entropy scoring for compression scheduling (MessageEntropyScorer)
- Incremental checkpointing (IncrementalCheckpointHooks)
- Claude Code hook integration (claude_code module)
"""

from ..hooks import CompressContext, CompressEvent, CompressionHooks
from .compaction import (
    EntropyScorer,
    InputPriorityHooks,
    PostCompactHookData,
    PreCompactHookData,
)
from .incremental_checkpoint import (
    Checkpoint,
    CheckpointStoreConfig,
    IncrementalCheckpointHooks,
    IncrementalCheckpointStore,
)
from .scoring import MessageEntropyScorer, MessageScore

__all__ = [
    "Checkpoint",
    "CheckpointStoreConfig",
    "CompressContext",
    "CompressEvent",
    "CompressionHooks",
    "EntropyScorer",
    "IncrementalCheckpointHooks",
    "IncrementalCheckpointStore",
    "InputPriorityHooks",
    "MessageEntropyScorer",
    "MessageScore",
    "PostCompactHookData",
    "PreCompactHookData",
]
