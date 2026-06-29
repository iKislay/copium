"""Vector index for semantic search over SharedContext entries.

Provides HNSW-based approximate nearest neighbor search over
shared context entries using embeddings. Reuses the memory system's
embedder infrastructure.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default embedding dimension (matches sentence-transformers/all-MiniLM-L6-v2)
DEFAULT_DIMENSION = 384


@dataclass
class VectorSearchResult:
    """A single search result with similarity score."""

    entry_id: str
    key: str
    similarity: float
    agent: str | None = None
    preview: str = ""


class VectorIndex:
    """SQLite-backed vector index for semantic search over context entries.

    Uses brute-force cosine similarity for simplicity and portability.
    For large-scale deployments, this can be swapped for HNSW via
    sqlite-vss or hnswlib.

    Args:
        db_path: Path to vector index database.
        dimension: Embedding vector dimension.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        dimension: int = DEFAULT_DIMENSION,
    ) -> None:
        self._dimension = dimension
        self._lock = threading.Lock()

        if db_path is None:
            vec_dir = Path.home() / ".copium"
            vec_dir.mkdir(parents=True, exist_ok=True)
            db_path = vec_dir / "shared_context_vectors.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create vector storage table."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS context_vectors (
                    entry_id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    agent TEXT,
                    vector BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    preview TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_cv_key
                    ON context_vectors(key);
                CREATE INDEX IF NOT EXISTS idx_cv_agent
                    ON context_vectors(agent);
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def add(
        self,
        entry_id: str,
        key: str,
        vector: list[float],
        *,
        agent: str | None = None,
        preview: str = "",
    ) -> None:
        """Add or update a vector for an entry."""
        if len(vector) != self._dimension:
            raise ValueError(
                f"Vector dimension mismatch: got {len(vector)}, expected {self._dimension}"
            )

        blob = self._vector_to_blob(vector)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO context_vectors
                    (entry_id, key, agent, vector, dimension, preview)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (entry_id, key, agent, blob, self._dimension, preview[:200]),
                )

    def remove(self, entry_id: str) -> None:
        """Remove a vector by entry ID."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM context_vectors WHERE entry_id = ?", (entry_id,)
                )

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        min_similarity: float = 0.0,
        agent_filter: str | None = None,
        key_filter: str | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar entries using cosine similarity.

        Args:
            query_vector: Query embedding vector.
            top_k: Maximum results to return.
            min_similarity: Minimum cosine similarity threshold.
            agent_filter: Optional filter by agent name.
            key_filter: Optional filter by key prefix.

        Returns:
            List of VectorSearchResult sorted by similarity (descending).
        """
        if len(query_vector) != self._dimension:
            raise ValueError(
                f"Query vector dimension mismatch: got {len(query_vector)}, expected {self._dimension}"
            )

        conditions = []
        params: list[Any] = []

        if agent_filter:
            conditions.append("agent = ?")
            params.append(agent_filter)
        if key_filter:
            conditions.append("key LIKE ?")
            params.append(f"{key_filter}%")

        where = " AND ".join(conditions) if conditions else "1=1"

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM context_vectors WHERE {where}",
                params,
            ).fetchall()

        # Compute cosine similarity for each candidate
        results: list[VectorSearchResult] = []
        for row in rows:
            stored_vector = self._blob_to_vector(row["vector"])
            similarity = self._cosine_similarity(query_vector, stored_vector)
            if similarity >= min_similarity:
                results.append(
                    VectorSearchResult(
                        entry_id=row["entry_id"],
                        key=row["key"],
                        similarity=similarity,
                        agent=row["agent"],
                        preview=row["preview"],
                    )
                )

        # Sort by similarity descending, take top_k
        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:top_k]

    def count(self) -> int:
        """Get total number of indexed vectors."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM context_vectors").fetchone()
        return row[0]

    def clear(self) -> None:
        """Remove all vectors."""
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM context_vectors")

    def _vector_to_blob(self, vector: list[float]) -> bytes:
        """Pack float vector to binary blob."""
        return struct.pack(f"{len(vector)}f", *vector)

    def _blob_to_vector(self, blob: bytes) -> list[float]:
        """Unpack binary blob to float vector."""
        count = len(blob) // 4  # 4 bytes per float32
        return list(struct.unpack(f"{count}f", blob))

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
