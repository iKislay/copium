"""Session archive compactor.

Compresses session archives by deduplicating tool outputs, collapsing
assistant preamble, removing ANSI noise, and grouping identical turns.
Uses the same dedup engine as the live SessionDedup transform.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from .archive import CompactConfig, CompactResult, SessionArchive, SessionMessage

logger = logging.getLogger(__name__)

# ANSI escape code patterns
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")
_SPINNER_PATTERN = re.compile(r"\r[^\n]*")
_CURSOR_PATTERN = re.compile(r"\x1b\[[0-9]*[ABCD]|\x1b\[2J|\x1b\[H")

# Assistant filler phrases to collapse
_PREAMBLE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(I'll |Let me |I will |I'm going to |Sure,? )", re.MULTILINE),
    re.compile(r"^(Here'?s? |Now |Alright,? |Okay,? |Great,? )", re.MULTILINE),
    re.compile(
        r"^(Looking at |Based on |According to |As (you|we) can see)",
        re.MULTILINE,
    ),
]


def _content_hash(text: str) -> str:
    """SHA-256 hash of content for exact dedup."""
    cleaned = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text).strip()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def _minhash_signature(text: str, num_perm: int = 128) -> list[int]:
    """Compute MinHash signature for near-duplicate detection."""
    import random

    cleaned = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text).strip()
    if len(cleaned) < 3:
        return [0] * num_perm

    shingles: set[int] = set()
    for i in range(len(cleaned) - 2):
        shingles.add(hash(cleaned[i : i + 3]))

    random.seed(42)
    primes = [random.randint(2**16, 2**31) for _ in range(num_perm)]
    offsets = [random.randint(0, 2**31) for _ in range(num_perm)]

    sig = []
    for p, o in zip(primes, offsets):
        min_val = float("inf")
        for s in shingles:
            val = (s * p + o) % (2**31)
            if val < min_val:
                min_val = val
        sig.append(int(min_val) if min_val != float("inf") else 0)

    return sig


def _jaccard_similarity(sig_a: list[int], sig_b: list[int]) -> float:
    """Estimate Jaccard similarity from MinHash signatures."""
    if not sig_a or not sig_b:
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return matches / len(sig_a)


class SessionCompactor:
    """Compress a session archive by deduplicating and removing noise."""

    def __init__(self, config: CompactConfig | None = None):
        self.config = config or CompactConfig()
        self._hash_index: dict[str, int] = {}  # hash -> first turn index
        self._sig_index: list[tuple[int, list[int]]] = []  # (turn_index, signature)

    def compact(self, archive: SessionArchive) -> tuple[SessionArchive, CompactResult]:
        """Compress an archive, returning new archive and stats."""
        result = CompactResult(
            original_messages=len(archive.messages),
            original_tokens_est=archive.token_estimate(),
        )

        messages = list(archive.messages)

        if self.config.remove_ansi:
            messages, ansi_count = self._remove_ansi(messages)
            result.ansi_stripped = ansi_count

        if self.config.deduplicate_tool_outputs:
            messages, exact_hits, near_hits = self._deduplicate_tool_outputs(messages)
            result.dedup_hits = exact_hits
            result.near_dedup_hits = near_hits

        if self.config.collapse_assistant_preamble:
            messages, preamble_count = self._collapse_assistant_preamble(messages)
            result.preamble_collapsed = preamble_count

        if self.config.group_identical_turns:
            messages = self._group_identical_turns(messages)

        # Build compacted archive
        compacted = SessionArchive(messages=messages)
        compacted._metadata = {
            **archive.metadata,
            "_copium_compacted": True,
            "_copium_original_messages": len(archive.messages),
            "_copium_original_tokens_est": result.original_tokens_est,
        }

        result.compacted_messages = len(messages)
        result.compacted_tokens_est = compacted.token_estimate()

        return compacted, result

    def _remove_ansi(
        self, messages: list[SessionMessage]
    ) -> tuple[list[SessionMessage], int]:
        """Strip ANSI escape codes and spinner sequences."""
        count = 0
        result = []
        for msg in messages:
            cleaned = _ANSI_PATTERN.sub("", msg.content)
            cleaned = _SPINNER_PATTERN.sub("", cleaned)
            cleaned = _CURSOR_PATTERN.sub("", cleaned)
            if cleaned != msg.content:
                count += 1
                msg = SessionMessage(
                    type=msg.type,
                    role=msg.role,
                    content=cleaned,
                    metadata=msg.metadata,
                    turn_index=msg.turn_index,
                )
            result.append(msg)
        return result, count

    def _deduplicate_tool_outputs(
        self, messages: list[SessionMessage]
    ) -> tuple[list[SessionMessage], int, int]:
        """Replace repeated tool outputs with reference markers."""
        exact_hits = 0
        near_hits = 0
        result = []
        hash_index: dict[str, int] = {}
        sig_index: list[tuple[int, list[int]]] = []

        for msg in messages:
            # Only dedup tool outputs with substantial content
            if msg.role != "tool" or len(msg.content) < self.config.min_content_length:
                result.append(msg)
                continue

            content_hash = _content_hash(msg.content)

            # Exact duplicate check
            if content_hash in hash_index:
                exact_hits += 1
                first_turn = hash_index[content_hash]
                marker = (
                    f"[Session dedup: Content identical to turn {first_turn} "
                    f"({len(msg.content)} chars). Refer to original above.]"
                )
                result.append(
                    SessionMessage(
                        type=msg.type,
                        role=msg.role,
                        content=marker,
                        metadata={**msg.metadata, "_dedup_ref": first_turn},
                        turn_index=msg.turn_index,
                    )
                )
                continue

            # Near-duplicate check via MinHash
            sig = _minhash_signature(msg.content)
            is_near_dup = False
            for ref_turn, ref_sig in sig_index:
                if _jaccard_similarity(sig, ref_sig) >= self.config.near_duplicate_threshold:
                    near_hits += 1
                    is_near_dup = True
                    marker = (
                        f"[Session dedup: Content near-identical to turn {ref_turn} "
                        f"({len(msg.content)} chars, ~{int(_jaccard_similarity(sig, ref_sig) * 100)}% similar). "
                        f"Refer to original above.]"
                    )
                    result.append(
                        SessionMessage(
                            type=msg.type,
                            role=msg.role,
                            content=marker,
                            metadata={**msg.metadata, "_dedup_ref": ref_turn},
                            turn_index=msg.turn_index,
                        )
                    )
                    break

            if not is_near_dup:
                hash_index[content_hash] = msg.turn_index
                sig_index.append((msg.turn_index, sig))
                result.append(msg)

        return result, exact_hits, near_hits

    def _collapse_assistant_preamble(
        self, messages: list[SessionMessage]
    ) -> tuple[list[SessionMessage], int]:
        """Remove filler phrases from assistant messages."""
        count = 0
        result = []
        for msg in messages:
            if msg.role != "assistant":
                result.append(msg)
                continue

            lines = msg.content.split("\n")
            collapsed_lines = []
            modified = False

            for line in lines:
                is_preamble = False
                for pattern in _PREAMBLE_PATTERNS:
                    if pattern.match(line.strip()) and len(line.strip()) < 100:
                        # Only collapse short filler lines, not substantive content
                        is_preamble = True
                        break
                if not is_preamble:
                    collapsed_lines.append(line)
                else:
                    modified = True

            if modified:
                count += 1
                new_content = "\n".join(collapsed_lines).strip()
                result.append(
                    SessionMessage(
                        type=msg.type,
                        role=msg.role,
                        content=new_content,
                        metadata=msg.metadata,
                        turn_index=msg.turn_index,
                    )
                )
            else:
                result.append(msg)

        return result, count

    def _group_identical_turns(
        self, messages: list[SessionMessage]
    ) -> list[SessionMessage]:
        """Merge consecutive identical user turns."""
        if not messages:
            return messages

        result = [messages[0]]
        for msg in messages[1:]:
            prev = result[-1]
            if (
                msg.role == "user"
                and prev.role == "user"
                and msg.content == prev.content
            ):
                # Skip duplicate consecutive user turn
                continue
            result.append(msg)

        return result
