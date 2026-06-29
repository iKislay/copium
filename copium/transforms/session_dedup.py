"""Session-level deduplication across conversation turns.

Tracks content hashes across the full conversation. When the same file or
tool output appears again, sends a reference marker instead of the full
content. Eliminates the "re-sent tool output" problem where identical
content rides along in context every turn.

Two-tier detection:
  1. Exact SHA-256 — catches byte-identical duplicate file reads
  2. MinHash LSH — catches near-duplicates (e.g. npm install with
     slightly different timing output)

Retrieval markers use the Pichay-proven bracketed format that models
recognize and act on without instruction.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from .base import Transform

logger = logging.getLogger(__name__)

# Content types eligible for dedup (tool outputs, file reads)
_DEDUP_ROLES: frozenset[str] = frozenset({"tool", "function", "tool_result"})
# Never dedup these roles
_SKIP_ROLES: frozenset[str] = frozenset({"system", "user"})
# Tool names that return file content (good dedup candidates)
_FILE_TOOLS: frozenset[str] = frozenset({
    "Read", "read", "Glob", "glob", "Grep", "grep",
    "cat", "head", "tail", "less", "more",
})
# Tool names that produce deterministic output (good dedup candidates)
_DETERMINISTIC_TOOLS: frozenset[str] = frozenset({
    "Bash", "bash", "ls", "find", "wc", "diff", "git",
})


def _content_hash(text: str) -> str:
    """SHA-256 hash of content, stripped of ANSI escape codes and trailing whitespace."""
    cleaned = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text).strip()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def _minhash_signature(text: str, num_perm: int = 128) -> list[int]:
    """Compute MinHash signature for near-duplicate detection.

    Uses 3-shingles (character trigrams) for robust near-duplicate detection
    that tolerates minor output variations (timestamps, timing differences).
    """
    cleaned = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text).strip()
    # 3-shingles
    if len(cleaned) < 3:
        return [0] * num_perm

    shingles: set[int] = set()
    for i in range(len(cleaned) - 2):
        shingle = cleaned[i : i + 3]
        shingles.add(hash(shingle))

    # MinHash with different hash functions
    import random

    random.seed(42)  # Deterministic for reproducibility
    primes = [random.randint(2**16, 2**31) for _ in range(num_perm)]
    offsets = [random.randint(0, 2**31) for _ in range(num_perm)]

    sig = []
    for p, o in zip(primes, offsets):
        min_val = float("inf")
        for s in shingles:
            val = (s * p + o) % (2**31)
            if val < min_val:
                min_val = val
        sig.append(min_val if min_val != float("inf") else 0)

    return sig


def _jaccard_similarity(sig_a: list[int], sig_b: list[int]) -> float:
    """Estimate Jaccard similarity from MinHash signatures."""
    if not sig_a or not sig_b:
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return matches / len(sig_a)


def _extract_tool_name(message: dict[str, Any]) -> str | None:
    """Extract tool name from a tool_result message."""
    # Anthropic format
    if "tool_call_id" in message or message.get("role") in ("tool", "tool_result"):
        return message.get("name") or message.get("tool_name")
    # OpenAI format
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                return part.get("tool_use_id", "").split("_")[0] if part.get("tool_use_id") else None
    return None


def _is_eligible_for_dedup(message: dict[str, Any]) -> bool:
    """Check if a message is eligible for deduplication."""
    role = message.get("role", "")

    # Never dedup system or user messages
    if role in _SKIP_ROLES:
        return False

    # Dedup tool results
    if role in _DEDUP_ROLES:
        return True

    # Dedup assistant messages that contain tool results
    if role == "assistant":
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    return True

    return False


def _get_content_text(message: dict[str, Any]) -> str | None:
    """Extract the main content text from a message."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "tool_result":
                    # Extract tool result content
                    result_content = part.get("content")
                    if isinstance(result_content, str):
                        texts.append(result_content)
                    elif isinstance(result_content, list):
                        for sub in result_content:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                texts.append(sub.get("text", ""))
        return "\n".join(texts) if texts else None
    return None


def _make_retrieval_marker(
    first_seen_turn: int,
    content_len: int,
    tool_name: str | None = None,
) -> str:
    """Create a Pichay-proven retrieval marker.

    Format: [Session dedup: <description>. Re-read if needed.]
    Models recognize and act on this without instruction.
    """
    desc = f"Content first seen at turn {first_seen_turn} ({content_len} chars)"
    if tool_name:
        desc = f"{tool_name} output first seen at turn {first_seen_turn} ({content_len} chars)"
    return f"[Session dedup: {desc}. Re-read the original source if needed.]"


@dataclass
class _DedupEntry:
    """Tracks a seen piece of content for deduplication."""

    content_hash: str
    minhash_sig: list[int]
    first_seen_turn: int
    content_len: int
    tool_name: str | None
    access_count: int = 1


@dataclass
class SessionDedupConfig:
    """Configuration for session-level deduplication.

    Tracks content hashes across the full conversation. When the same
    file or tool output appears again, sends a reference marker instead
    of the full content. Eliminates the re-sent tool output problem.

    Two-tier detection:
      - Exact SHA-256 catches byte-identical duplicates
      - MinHash LSH catches near-duplicates (same command, slightly
        different output)

    Retrieval markers use the Pichay-proven bracketed format that
    models recognize and act on without instruction.
    """

    enabled: bool = True

    # Exact hash matching (SHA-256)
    exact_hash: bool = True

    # Near-duplicate detection via MinHash
    minhash_enabled: bool = True
    minhash_threshold: float = 0.85  # Jaccard similarity threshold
    minhash_num_perm: int = 128  # Number of permutation functions

    # Session limits
    max_session_hashes: int = 10_000  # Evict oldest if exceeded

    # Minimum content length to bother deduplicating (chars)
    min_content_length: int = 200

    # Content types eligible for dedup
    # "all" = any tool output, "file" = file reads only, "deterministic" = predictable output
    eligible_content: str = "all"

    # Per-tool dedup aggressiveness — lower threshold = more aggressive dedup
    # These override minhash_threshold for specific tools to account for
    # typical output variance (e.g., grep output is often near-identical
    # across invocations, so a lower threshold catches more duplicates).
    tool_dedup_profiles: dict[str, float] = field(default_factory=lambda: {
        "Grep": 0.70,    # Lower threshold for grep (near-duplicates common)
        "grep": 0.70,
        "Read": 0.90,    # High threshold for reads (exact match preferred)
        "read": 0.90,
        "cat": 0.90,
        "Bash": 0.80,    # Medium threshold for bash (timing varies)
        "bash": 0.80,
        "Glob": 0.95,    # Very high threshold for glob (mostly identical)
        "glob": 0.95,
        "find": 0.80,
        "ls": 0.85,
    })


class SessionDedup(Transform):
    """Session-level deduplication across conversation turns.

    When the same file or tool output appears multiple times in a
    conversation, keeps only the first occurrence in full and replaces
    subsequent occurrences with retrieval markers. The original content
    remains accessible via the retrieval marker.

    Benefits:
      - Eliminates 85%+ of re-sent tool output (ContextZip measurement)
      - Works across all turns, not just within a single request
      - Two-tier detection catches both exact and near-duplicates
      - Retrieval markers are self-descriptive and LLM-actionable
    """

    name = "session_dedup"

    def __init__(self, config: SessionDedupConfig | None = None):
        self.config = config or SessionDedupConfig()
        # Turn-level hash table: content_hash -> _DedupEntry
        self._seen: dict[str, _DedupEntry] = {}
        self._turn_counter: int = 0

    def _evict_oldest(self) -> None:
        """Evict oldest entries when the hash table is full."""
        if len(self._seen) <= self.config.max_session_hashes:
            return
        # Sort by first_seen_turn, remove oldest 20%
        to_remove = len(self._seen) - int(self.config.max_session_hashes * 0.8)
        sorted_entries = sorted(self._seen.items(), key=lambda x: x[1].first_seen_turn)
        for hash_key, _ in sorted_entries[:to_remove]:
            del self._seen[hash_key]

    def _find_near_duplicate(
        self, minhash_sig: list[int], tool_name: str | None = None
    ) -> tuple[str, _DedupEntry] | None:
        """Find a near-duplicate entry using MinHash similarity.

        Uses tool-specific thresholds when available — e.g., grep output
        gets a lower threshold (0.70) since near-identical results are
        common across invocations.
        """
        # Use tool-specific threshold if available, otherwise global default
        threshold = self.config.minhash_threshold
        if tool_name and tool_name in self.config.tool_dedup_profiles:
            threshold = self.config.tool_dedup_profiles[tool_name]

        best_hash: str | None = None
        best_entry: _DedupEntry | None = None
        best_sim = 0.0

        for hash_key, entry in self._seen.items():
            if entry.minhash_sig is None:
                continue
            sim = _jaccard_similarity(minhash_sig, entry.minhash_sig)
            if sim > best_sim and sim >= threshold:
                best_sim = sim
                best_hash = hash_key
                best_entry = entry

        if best_hash and best_entry:
            return best_hash, best_entry
        return None

    def _process_message(
        self,
        message: dict[str, Any],
        turn_index: int,
    ) -> dict[str, Any] | None:
        """Process a single message for deduplication.

        Returns None if the message was deduplicated (replaced by marker),
        or the original/modified message otherwise.
        """
        if not _is_eligible_for_dedup(message):
            return message

        content_text = _get_content_text(message)
        if content_text is None or len(content_text) < self.config.min_content_length:
            return message

        tool_name = _extract_tool_name(message)

        # Check eligible content type
        if self.config.eligible_content == "file" and tool_name not in _FILE_TOOLS:
            return message
        if self.config.eligible_content == "deterministic" and tool_name not in _DETERMINISTIC_TOOLS:
            return message

        content_hash = _content_hash(content_text)

        # Tier 1: Exact hash match
        if self.config.exact_hash and content_hash in self._seen:
            entry = self._seen[content_hash]
            entry.access_count += 1
            marker = _make_retrieval_marker(
                first_seen_turn=entry.first_seen_turn,
                content_len=entry.content_len,
                tool_name=entry.tool_name,
            )
            logger.debug(
                "Session dedup: exact match for hash %s (first seen turn %d, access #%d)",
                content_hash[:8],
                entry.first_seen_turn,
                entry.access_count,
            )
            # Return a new message with the marker replacing the content
            deduped = dict(message)
            deduped["content"] = marker
            deduped["_copium_session_dedup"] = True
            deduped["_copium_dedup_hash"] = content_hash
            return deduped

        # Tier 2: Near-duplicate match (MinHash)
        if self.config.minhash_enabled:
            minhash_sig = _minhash_signature(content_text, self.config.minhash_num_perm)
            near_dup = self._find_near_duplicate(minhash_sig, tool_name)
            if near_dup is not None:
                near_hash, near_entry = near_dup
                near_entry.access_count += 1
                marker = _make_retrieval_marker(
                    first_seen_turn=near_entry.first_seen_turn,
                    content_len=near_entry.content_len,
                    tool_name=near_entry.tool_name,
                )
                logger.debug(
                    "Session dedup: near-duplicate match (sim > %.2f) for hash %s "
                    "(first seen turn %d, access #%d)",
                    self.config.minhash_threshold,
                    near_hash[:8],
                    near_entry.first_seen_turn,
                    near_entry.access_count,
                )
                deduped = dict(message)
                deduped["content"] = marker
                deduped["_copium_session_dedup"] = True
                deduped["_copium_dedup_hash"] = near_hash
                return deduped
        else:
            minhash_sig = []

        # No match — register this content
        entry = _DedupEntry(
            content_hash=content_hash,
            minhash_sig=minhash_sig if self.config.minhash_enabled else [],
            first_seen_turn=turn_index,
            content_len=len(content_text),
            tool_name=tool_name,
        )
        self._seen[content_hash] = entry
        self._evict_oldest()
        return message

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Apply session-level deduplication across messages.

        Processes all messages, tracking content hashes. When a duplicate
        is found, replaces it with a retrieval marker. The original content
        is still accessible via the marker.
        """
        if not self.config.enabled:
            return TransformResult(
                messages=messages,
                tokens_before=tokenizer.count_messages(messages),
                tokens_after=tokenizer.count_messages(messages),
                transforms_applied=[],
            )

        frozen_count = kwargs.get("frozen_message_count", 0)
        tokens_before = tokenizer.count_messages(messages)

        result_messages: list[dict[str, Any]] = []
        transforms_applied: list[str] = []
        markers_inserted: list[str] = []
        dedup_count = 0

        for i, msg in enumerate(messages):
            # Skip frozen messages (cached prefix)
            if i < frozen_count:
                result_messages.append(msg)
                continue

            self._turn_counter = i
            processed = self._process_message(msg, turn_index=i)

            if processed is None or processed is not msg:
                # Message was deduplicated
                dedup_count += 1
                result_messages.append(processed if processed is not None else msg)
                transforms_applied.append("session_dedup:marker")
                if processed and "_copium_dedup_hash" in processed:
                    markers_inserted.append(processed["_copium_dedup_hash"])
            else:
                result_messages.append(msg)

        tokens_after = tokenizer.count_messages(result_messages)

        if dedup_count > 0:
            logger.info(
                "Session dedup: %d messages deduplicated, %d -> %d tokens (saved %d)",
                dedup_count,
                tokens_before,
                tokens_after,
                tokens_before - tokens_after,
            )

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
            markers_inserted=markers_inserted,
        )
