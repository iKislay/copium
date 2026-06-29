"""Session expander — reconstruct original sessions from compacted archives.

Reverses compaction by restoring deduplicated content from the CCR store
or from inline references within the archive.

Recovery sources (in priority order):
1. CCR store (hash-keyed retrieval, sub-millisecond)
2. Original archive file (if provided)
3. Best-effort (leave self-descriptive markers in place)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Protocol

from .archive import SessionArchive, SessionMessage

logger = logging.getLogger(__name__)

# Pattern to match dedup reference markers
_DEDUP_REF_PATTERN = re.compile(
    r"\[Session dedup: Content (?:identical|near-identical) to turn (\d+)"
)

# Pattern to match CCR hash markers embedded in metadata
_CCR_HASH_PATTERN = re.compile(r"[a-f0-9]{16}")


class CCRStoreBridge(Protocol):
    """Protocol for CCR store access (decoupled from concrete implementation)."""

    def get(self, hash_key: str) -> str | None:
        """Retrieve original content by hash key."""
        ...

    def has(self, hash_key: str) -> bool:
        """Check if a hash key exists in the store."""
        ...


class SessionExpander:
    """Reconstruct original session from a compacted archive.

    Supports three recovery strategies:
    1. CCR store: hash-keyed retrieval from the compression store
    2. Original archive: exact reconstruction from the uncompacted file
    3. Best-effort: leave markers in place (models understand them)
    """

    def __init__(
        self,
        *,
        original_path: Path | None = None,
        ccr_store: CCRStoreBridge | None = None,
    ):
        """Initialize expander.

        Args:
            original_path: Path to the original (uncompacted) archive for
                          full reconstruction. If not provided, expansion
                          is best-effort using inline references.
            ccr_store: Optional CCR store bridge for hash-keyed retrieval.
                      When available, this is the preferred recovery source.
        """
        self._original: SessionArchive | None = None
        self._ccr_store = ccr_store
        if original_path and original_path.exists():
            self._original = SessionArchive(original_path)

    def expand(self, compacted: SessionArchive) -> SessionArchive:
        """Restore original messages from reference markers.

        Recovery priority:
        1. CCR store (if available and content found by hash)
        2. Original archive (if provided)
        3. Best-effort (leave self-descriptive markers)
        """
        if not compacted.is_compacted:
            logger.info("Archive is not compacted, returning as-is")
            return compacted

        # Try CCR store first (fastest, most reliable)
        if self._ccr_store:
            return self._expand_from_ccr(compacted)

        if self._original:
            return self._expand_from_original(compacted)

        return self._expand_best_effort(compacted)

    def _expand_from_ccr(self, compacted: SessionArchive) -> SessionArchive:
        """Expand using the CCR store for hash-keyed retrieval."""
        expanded_messages: list[SessionMessage] = []
        ccr_hits = 0
        ccr_misses = 0

        for msg in compacted.messages:
            # Check if this message has a CCR hash in metadata
            ccr_hash = msg.metadata.get("_ccr_hash")
            if ccr_hash and self._ccr_store:
                content = self._ccr_store.get(ccr_hash)
                if content:
                    ccr_hits += 1
                    expanded_messages.append(
                        SessionMessage(
                            type=msg.type,
                            role=msg.role,
                            content=content,
                            metadata={
                                k: v
                                for k, v in msg.metadata.items()
                                if not k.startswith("_")
                            },
                            turn_index=msg.turn_index,
                        )
                    )
                    continue
                else:
                    ccr_misses += 1

            # Check if this is a dedup reference with content_hash
            content_hash = msg.metadata.get("_content_hash")
            if content_hash and self._ccr_store:
                content = self._ccr_store.get(content_hash)
                if content:
                    ccr_hits += 1
                    expanded_messages.append(
                        SessionMessage(
                            type=msg.type,
                            role=msg.role,
                            content=content,
                            metadata={
                                k: v
                                for k, v in msg.metadata.items()
                                if not k.startswith("_")
                            },
                            turn_index=msg.turn_index,
                        )
                    )
                    continue

            # Fall back to original archive if CCR miss
            if self._original and _DEDUP_REF_PATTERN.search(msg.content):
                ref_match = _DEDUP_REF_PATTERN.search(msg.content)
                if ref_match and "_dedup_ref" in msg.metadata:
                    ref_turn = int(ref_match.group(1))
                    for orig_msg in self._original.messages:
                        if orig_msg.turn_index == ref_turn and orig_msg.role == "tool":
                            expanded_messages.append(
                                SessionMessage(
                                    type=msg.type,
                                    role=msg.role,
                                    content=orig_msg.content,
                                    metadata={
                                        k: v
                                        for k, v in msg.metadata.items()
                                        if not k.startswith("_")
                                    },
                                    turn_index=msg.turn_index,
                                )
                            )
                            break
                    else:
                        expanded_messages.append(msg)
                    continue

            expanded_messages.append(msg)

        logger.info(
            "CCR expansion: %d hits, %d misses out of %d messages",
            ccr_hits,
            ccr_misses,
            len(compacted.messages),
        )

        result = SessionArchive(messages=expanded_messages)
        result._metadata = {
            k: v
            for k, v in compacted.metadata.items()
            if not k.startswith("_copium_")
        }
        return result

    def _expand_from_original(self, compacted: SessionArchive) -> SessionArchive:
        """Expand using the original archive as source of truth."""
        # Build index of original messages by turn
        turn_content: dict[int, str] = {}
        for msg in self._original.messages:  # type: ignore[union-attr]
            if msg.role == "tool":
                turn_content[msg.turn_index] = msg.content

        expanded_messages: list[SessionMessage] = []
        for msg in compacted.messages:
            ref_match = _DEDUP_REF_PATTERN.search(msg.content)
            if ref_match and "_dedup_ref" in msg.metadata:
                ref_turn = int(ref_match.group(1))
                original_content = turn_content.get(ref_turn, msg.content)
                expanded_messages.append(
                    SessionMessage(
                        type=msg.type,
                        role=msg.role,
                        content=original_content,
                        metadata={
                            k: v
                            for k, v in msg.metadata.items()
                            if k != "_dedup_ref"
                        },
                        turn_index=msg.turn_index,
                    )
                )
            else:
                expanded_messages.append(msg)

        result = SessionArchive(messages=expanded_messages)
        result._metadata = {
            k: v
            for k, v in compacted.metadata.items()
            if not k.startswith("_copium_")
        }
        return result

    def _expand_best_effort(self, compacted: SessionArchive) -> SessionArchive:
        """Best-effort expansion without original archive.

        Dedup markers are self-descriptive, so models can follow them.
        This method just strips the _copium_compacted flag.
        """
        logger.warning(
            "No original archive available for full expansion. "
            "Reference markers will remain in place."
        )

        result = SessionArchive(messages=list(compacted.messages))
        result._metadata = {
            k: v
            for k, v in compacted.metadata.items()
            if not k.startswith("_copium_")
        }
        return result
