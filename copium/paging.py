"""Cold/Hot context paging — virtual memory for LLM context.

Inspired by the Pichay paper (arXiv:2603.09023) which proved 93%
context reduction with 0.0254% fault rate using virtual memory paging.

Key concepts:
- **Hot Context**: Active working set in the context window (RAM equivalent)
- **Cold Context**: Overflow stored in SQLite (disk equivalent)
- **Page Fault**: When the model references a tool output that was paged out,
  the system retrieves it from cold storage and re-inserts it (with a
  CONTEXT-PAGE-NNN marker for traceability)
- **Eviction Policy**: FIFO with τ=4 turns (evict content older than 4 turns)
- **Fault-Driven Pinning**: Content involved in errors or referenced by
  the model is "pinned" and not evicted (like mlock in virtual memory)

Phantom tools (Pichay-proven):
- `memory_release(page_id)`: Explicitly page out content
- `memory_fault(page_id, hint)`: Hint to prefetch or reprioritize

The pipeline integration:
1. After ContentRouter, check if context exceeds budget
2. Evict cold content (old tool outputs) to SQLite
3. Leave retrieval markers in place of evicted content
4. On fault (model references evicted content), retrieve from SQLite
5. Pin content that was faulted on (don't evict again)
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EvictionPolicy(Enum):
    """Page eviction policies."""

    FIFO = "fifo"  # First In, First Out (τ=4 turns)
    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    IMPORTANCE = "importance"  # Score-based (error content pinned)


class PageStatus(Enum):
    """Page status in the store."""

    HOT = "hot"  # In context window
    COLD = "cold"  # Paged out to SQLite
    PINNED = "pinned"  # Pinned (won't be evicted)
    FAULTED = "faulted"  # Was faulted on, now hot again


@dataclass
class Page:
    """A page of context that can be hot (in context) or cold (in store)."""

    page_id: str  # Unique identifier (SHA-256 of content)
    content: str  # The actual content
    role: str  # Message role (tool, assistant, user)
    turn_index: int  # Which conversation turn this came from
    token_count: int  # Approximate token count
    status: PageStatus = PageStatus.HOT

    # Metadata
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    pinned: bool = False
    pin_reason: str = ""

    # Compression info
    original_tokens: int = 0  # Before compression
    compressed: bool = False

    def touch(self) -> None:
        """Record an access (for LRU/LFU)."""
        self.last_accessed = time.time()
        self.access_count += 1

    def to_marker(self) -> str:
        """Convert to a retrieval marker for the context window."""
        return (
            f"[CONTEXT-PAGE-{self.page_id[:8]}]\n"
            f"Content paged out (role={self.role}, turn={self.turn_index}).\n"
            f"Use memory_fault(page_id='{self.page_id[:8]}') to retrieve.\n"
            f"[/CONTEXT-PAGE-{self.page_id[:8]}]"
        )


@dataclass
class PageFault:
    """Record of a page fault (model referenced evicted content)."""

    page_id: str
    fault_time: float = field(default_factory=time.time)
    turn_index: int = 0
    hint: str = ""


@dataclass
class PagingConfig:
    """Configuration for cold/hot context paging.

    Uses virtual memory-style paging to manage context overflow.
    Content older than τ turns is evicted to cold storage (SQLite)
    and replaced with retrieval markers. Faults (model references
    evicted content) trigger retrieval and pinning.

    Based on Pichay (arXiv:2603.09023): 93% context reduction,
    0.0254% fault rate with FIFO eviction at τ=4.
    """

    enabled: bool = True

    # Eviction policy
    eviction_policy: str = "fifo"  # fifo, lru, lfu, importance
    eviction_tau: int = 4  # Turns to keep before eviction (FIFO)

    # Storage
    store_path: str | None = None  # SQLite path (None = in-memory)
    max_cold_pages: int = 1000  # Max pages in cold storage

    # Page fault handling
    max_faults_per_turn: int = 3  # Max faults before warning
    auto_pin_on_fault: bool = True  # Pin content that was faulted

    # Context budget
    hot_context_budget: float = 0.8  # % of context to keep hot
    reserve_for_markers: int = 200  # Tokens reserved for page markers

    # Phantom tools
    enable_phantom_tools: bool = True  # memory_release, memory_fault

    # Debug
    log_evictions: bool = True
    log_faults: bool = True


class PageStore:
    """SQLite-backed page store for cold context.

    Stores evicted pages in SQLite for later retrieval. Supports
    FIFO, LRU, LFU, and importance-based eviction policies.
    """

    def __init__(self, config: PagingConfig):
        self.config = config
        self._db: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite database."""
        if self.config.store_path:
            self._db = sqlite3.connect(self.config.store_path)
        else:
            self._db = sqlite3.connect(":memory:")

        self._db.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                page_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                role TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                token_count INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'cold',
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                pin_reason TEXT DEFAULT '',
                original_tokens INTEGER DEFAULT 0,
                compressed INTEGER DEFAULT 0
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS faults (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id TEXT NOT NULL,
                fault_time REAL NOT NULL,
                turn_index INTEGER NOT NULL,
                hint TEXT DEFAULT '',
                FOREIGN KEY (page_id) REFERENCES pages(page_id)
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status)
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pages_turn ON pages(turn_index)
        """)
        self._db.commit()

    def store_page(self, page: Page) -> None:
        """Store a page in cold storage."""
        if self._db is None:
            return

        # Enforce max cold pages
        cold_count = self._count_cold_pages()
        if cold_count >= self.config.max_cold_pages:
            self._evict_oldest_cold()

        self._db.execute(
            """
            INSERT OR REPLACE INTO pages
            (page_id, content, role, turn_index, token_count, status,
             created_at, last_accessed, access_count, pinned, pin_reason,
             original_tokens, compressed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                page.page_id,
                page.content,
                page.role,
                page.turn_index,
                page.token_count,
                page.status.value,
                page.created_at,
                page.last_accessed,
                page.access_count,
                1 if page.pinned else 0,
                page.pin_reason,
                page.original_tokens,
                1 if page.compressed else 0,
            ),
        )
        self._db.commit()

    def retrieve_page(self, page_id: str) -> Page | None:
        """Retrieve a page from cold storage."""
        if self._db is None:
            return None

        cursor = self._db.execute(
            "SELECT * FROM pages WHERE page_id = ?", (page_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return Page(
            page_id=row[0],
            content=row[1],
            role=row[2],
            turn_index=row[3],
            token_count=row[4],
            status=PageStatus(row[5]),
            created_at=row[6],
            last_accessed=row[7],
            access_count=row[8],
            pinned=bool(row[9]),
            pin_reason=row[10] or "",
            original_tokens=row[11] or 0,
            compressed=bool(row[12]),
        )

    def remove_page(self, page_id: str) -> None:
        """Remove a page from cold storage."""
        if self._db is None:
            return
        self._db.execute("DELETE FROM pages WHERE page_id = ?", (page_id,))
        self._db.commit()

    def get_eviction_candidates(self, current_turn: int) -> list[Page]:
        """Get pages eligible for eviction based on policy."""
        if self._db is None:
            return []

        policy = EvictionPolicy(self.config.eviction_policy)

        if policy == EvictionPolicy.FIFO:
            # Evict pages older than τ turns, not pinned
            cutoff_turn = current_turn - self.config.eviction_tau
            cursor = self._db.execute(
                """
                SELECT * FROM pages
                WHERE turn_index < ? AND pinned = 0 AND status = 'hot'
                ORDER BY turn_index ASC
            """,
                (cutoff_turn,),
            )
        elif policy == EvictionPolicy.LRU:
            cursor = self._db.execute(
                """
                SELECT * FROM pages
                WHERE pinned = 0 AND status = 'hot'
                ORDER BY last_accessed ASC
                LIMIT 10
            """
            )
        elif policy == EvictionPolicy.LFU:
            cursor = self._db.execute(
                """
                SELECT * FROM pages
                WHERE pinned = 0 AND status = 'hot'
                ORDER BY access_count ASC
                LIMIT 10
            """
            )
        else:  # IMPORTANCE
            cursor = self._db.execute(
                """
                SELECT * FROM pages
                WHERE pinned = 0 AND status = 'hot'
                ORDER BY access_count DESC, token_count DESC
                LIMIT 10
            """
            )

        return [self._row_to_page(row) for row in cursor.fetchall()]

    def record_fault(self, page_id: str, turn_index: int, hint: str = "") -> None:
        """Record a page fault."""
        if self._db is None:
            return
        self._db.execute(
            "INSERT INTO faults (page_id, fault_time, turn_index, hint) VALUES (?, ?, ?, ?)",
            (page_id, time.time(), turn_index, hint),
        )
        self._db.commit()

    def get_fault_count(self, page_id: str) -> int:
        """Get the number of faults for a page."""
        if self._db is None:
            return 0
        cursor = self._db.execute(
            "SELECT COUNT(*) FROM faults WHERE page_id = ?", (page_id,)
        )
        return cursor.fetchone()[0]

    def _count_cold_pages(self) -> int:
        """Count pages in cold storage."""
        if self._db is None:
            return 0
        cursor = self._db.execute(
            "SELECT COUNT(*) FROM pages WHERE status = 'cold'"
        )
        return cursor.fetchone()[0]

    def _evict_oldest_cold(self) -> None:
        """Remove the oldest cold page to make room."""
        if self._db is None:
            return
        self._db.execute(
            """
            DELETE FROM pages WHERE page_id = (
                SELECT page_id FROM pages
                WHERE status = 'cold' AND pinned = 0
                ORDER BY created_at ASC
                LIMIT 1
            )
        """
        )
        self._db.commit()

    def _row_to_page(self, row: tuple) -> Page:
        """Convert a database row to a Page object."""
        return Page(
            page_id=row[0],
            content=row[1],
            role=row[2],
            turn_index=row[3],
            token_count=row[4],
            status=PageStatus(row[5]),
            created_at=row[6],
            last_accessed=row[7],
            access_count=row[8],
            pinned=bool(row[9]),
            pin_reason=row[10] or "",
            original_tokens=row[11] or 0,
            compressed=bool(row[12]),
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None


class PagingManager:
    """Manages hot/cold context paging for the pipeline.

    Coordinates page eviction, fault handling, and marker insertion.
    """

    def __init__(self, config: PagingConfig):
        self.config = config
        self.store = PageStore(config)
        self._pages: dict[str, Page] = {}  # page_id → Page
        self._faults: list[PageFault] = []
        self._current_turn: int = 0
        self._evicted_count: int = 0
        self._faulted_count: int = 0

    def register_page(self, content: str, role: str, token_count: int) -> str:
        """Register a piece of content as a page. Returns page_id."""
        page_id = hashlib.sha256(content.encode()).hexdigest()[:16]

        if page_id not in self._pages:
            page = Page(
                page_id=page_id,
                content=content,
                role=role,
                turn_index=self._current_turn,
                token_count=token_count,
                status=PageStatus.HOT,
            )
            self._pages[page_id] = page
            # Also write to store so eviction candidates can find it
            self.store.store_page(page)
        else:
            self._pages[page_id].touch()
            self.store.store_page(self._pages[page_id])

        return page_id

    def advance_turn(self) -> None:
        """Advance to the next conversation turn."""
        self._current_turn += 1

    def evict_cold_content(self, token_budget: int) -> tuple[list[str], int]:
        """Evict content that exceeds the token budget.

        Returns (list of page_ids evicted, tokens freed).
        """
        if not self.config.enabled:
            return [], 0

        # Calculate current hot token count
        hot_tokens = sum(
            p.token_count
            for p in self._pages.values()
            if p.status == PageStatus.HOT
        )

        if hot_tokens <= token_budget:
            return [], 0

        tokens_to_free = hot_tokens - token_budget
        freed = 0
        evicted_ids: list[str] = []

        # Get eviction candidates
        candidates = self.store.get_eviction_candidates(self._current_turn)

        for page in candidates:
            if freed >= tokens_to_free:
                break

            # Evict the page
            page.status = PageStatus.COLD
            self.store.store_page(page)
            # Sync back to in-memory dict
            if page.page_id in self._pages:
                self._pages[page.page_id].status = PageStatus.COLD
            freed += page.token_count
            evicted_ids.append(page.page_id)
            self._evicted_count += 1

            if self.config.log_evictions:
                logger.info(
                    "Paged out: %s (role=%s, turn=%d, %d tokens)",
                    page.page_id[:8],
                    page.role,
                    page.turn_index,
                    page.token_count,
                )

        return evicted_ids, freed

    def handle_fault(self, page_id: str, hint: str = "") -> Page | None:
        """Handle a page fault — retrieve evicted content.

        Returns the page if found, None otherwise.
        """
        # Check if the page exists in hot memory
        full_id = self._find_page_id(page_id)
        if full_id and full_id in self._pages:
            page = self._pages[full_id]
            if page.status == PageStatus.COLD:
                # Page fault: retrieve from cold storage
                page.status = PageStatus.HOT
                page.touch()
                self.store.record_fault(full_id, self._current_turn, hint)
                self._faulted_count += 1

                if self.config.auto_pin_on_fault:
                    page.pinned = True
                    page.pin_reason = "faulted"

                if self.config.log_faults:
                    logger.info(
                        "Page fault: %s (role=%s, turn=%d)",
                        full_id[:8],
                        page.role,
                        page.turn_index,
                    )

                return page

        # Try retrieving from store
        page = self.store.retrieve_page(page_id)
        if page is None:
            # Try with full ID
            page = self.store.retrieve_page(full_id or page_id)

        if page:
            page.status = PageStatus.HOT
            page.touch()
            self.store.record_fault(page.page_id, self._current_turn, hint)
            self._faulted_count += 1
            self._pages[page.page_id] = page

            if self.config.auto_pin_on_fault:
                page.pinned = True
                page.pin_reason = "faulted"

            if self.config.log_faults:
                logger.info(
                    "Page fault (from cold): %s (role=%s, turn=%d)",
                    page.page_id[:8],
                    page.role,
                    page.turn_index,
                )

        return page

    def pin_page(self, page_id: str, reason: str = "explicit") -> bool:
        """Pin a page to prevent eviction."""
        full_id = self._find_page_id(page_id)
        if full_id and full_id in self._pages:
            self._pages[full_id].pinned = True
            self._pages[full_id].pin_reason = reason
            return True
        return False

    def _find_page_id(self, partial_id: str) -> str | None:
        """Find a full page ID from a partial ID prefix."""
        if partial_id in self._pages:
            return partial_id
        for pid in self._pages:
            if pid.startswith(partial_id):
                return pid
        return None

    def get_stats(self) -> dict[str, Any]:
        """Get paging statistics."""
        hot_count = sum(
            1 for p in self._pages.values() if p.status == PageStatus.HOT
        )
        cold_count = self.store._count_cold_pages()
        pinned_count = sum(1 for p in self._pages.values() if p.pinned)
        hot_tokens = sum(
            p.token_count
            for p in self._pages.values()
            if p.status == PageStatus.HOT
        )

        return {
            "hot_pages": hot_count,
            "cold_pages": cold_count,
            "pinned_pages": pinned_count,
            "hot_tokens": hot_tokens,
            "total_pages": len(self._pages),
            "evictions": self._evicted_count,
            "faults": self._faulted_count,
            "fault_rate": (
                self._faulted_count / max(1, self._evicted_count)
                if self._evicted_count > 0
                else 0.0
            ),
        }

    def close(self) -> None:
        """Clean up resources."""
        self.store.close()
