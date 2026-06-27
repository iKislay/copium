"""Session expander — reconstruct original sessions from compacted archives.

Reverses compaction by restoring deduplicated content from the CCR store
or from inline references within the archive.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .archive import SessionArchive, SessionMessage

logger = logging.getLogger(__name__)

# Pattern to match dedup reference markers
_DEDUP_REF_PATTERN = re.compile(
    r"\[Session dedup: Content (?:identical|near-identical) to turn (\d+)"
)


class SessionExpander:
    """Reconstruct original session from a compacted archive."""

    def __init__(self, *, original_path: Path | None = None):
        """Initialize expander.

        Args:
            original_path: Path to the original (uncompacted) archive for
                          full reconstruction. If not provided, expansion
                          is best-effort using inline references.
        """
        self._original: SessionArchive | None = None
        if original_path and original_path.exists():
            self._original = SessionArchive(original_path)

    def expand(self, compacted: SessionArchive) -> SessionArchive:
        """Restore original messages from reference markers.

        If the original archive is available, uses it for exact reconstruction.
        Otherwise, leaves reference markers in place (they're self-descriptive
        and models can work with them).
        """
        if not compacted.is_compacted:
            logger.info("Archive is not compacted, returning as-is")
            return compacted

        if self._original:
            return self._expand_from_original(compacted)

        return self._expand_best_effort(compacted)

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
