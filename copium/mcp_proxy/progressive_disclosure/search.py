"""BM25 search backend for tool discovery.

Provides fast, dependency-free tool search using BM25 scoring.
Indexes tool names, descriptions, and parameter names for
high-quality semantic matching without ML dependencies.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    """A search result with score and tool metadata."""

    tool_name: str
    score: float
    summary: str = ""


class BM25Index:
    """BM25 search index for tool discovery.

    Indexes tool metadata (name, description, parameter names) and
    provides fast ranked retrieval by natural language query.

    Parameters:
        k1: Term frequency saturation. Default 1.5.
        b: Length normalization. Default 0.75.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._documents: list[tuple[str, list[str]]] = []  # (tool_name, tokens)
        self._doc_lengths: list[int] = []
        self._avg_doc_length: float = 0.0
        self._df: Counter[str] = Counter()  # document frequency per term
        self._n_docs: int = 0
        self._tool_summaries: dict[str, str] = {}

    def index_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        summary: str = "",
    ) -> None:
        """Add a tool to the index."""
        # Build document from name, description, and parameter names
        tokens = self._tokenize(name)
        tokens.extend(self._tokenize(description))

        if parameters:
            props = parameters.get("properties", {})
            for param_name in props:
                tokens.extend(self._tokenize(param_name))

        self._documents.append((name, tokens))
        self._doc_lengths.append(len(tokens))
        self._tool_summaries[name] = summary or f"{name}: {description[:100]}"

        # Update document frequency
        unique_terms = set(tokens)
        for term in unique_terms:
            self._df[term] += 1

        self._n_docs += 1
        self._avg_doc_length = sum(self._doc_lengths) / max(self._n_docs, 1)

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        """Search for tools matching the query.

        Args:
            query: Natural language search query.
            top_k: Maximum results to return.

        Returns:
            Ranked list of SearchResults.
        """
        if not self._documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: list[tuple[float, str]] = []
        for idx, (tool_name, doc_tokens) in enumerate(self._documents):
            score = self._score_document(query_tokens, doc_tokens, idx)
            if score > 0:
                scores.append((score, tool_name))

        scores.sort(reverse=True)
        results: list[SearchResult] = []
        for score, tool_name in scores[:top_k]:
            results.append(SearchResult(
                tool_name=tool_name,
                score=score,
                summary=self._tool_summaries.get(tool_name, ""),
            ))
        return results

    def _score_document(
        self, query_tokens: list[str], doc_tokens: list[str], doc_idx: int
    ) -> float:
        """Calculate BM25 score for a document."""
        doc_len = self._doc_lengths[doc_idx]
        score = 0.0
        doc_tf = Counter(doc_tokens)

        for term in query_tokens:
            if term not in doc_tf:
                continue

            tf = doc_tf[term]
            df = self._df.get(term, 0)

            # IDF component
            idf = math.log(
                (self._n_docs - df + 0.5) / (df + 0.5) + 1.0
            )

            # TF saturation with length normalization
            numerator = tf * (self._k1 + 1)
            denominator = tf + self._k1 * (
                1 - self._b + self._b * doc_len / self._avg_doc_length
            )
            score += idf * (numerator / denominator)

        return score

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into searchable terms."""
        # Split on non-alphanumeric, lowcase
        text = text.lower()
        # Split camelCase and snake_case
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        text = text.replace("_", " ").replace("-", " ")
        tokens = re.findall(r"[a-z0-9]+", text)
        # Filter stopwords
        return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]

    def clear(self) -> None:
        """Clear the index."""
        self._documents.clear()
        self._doc_lengths.clear()
        self._df.clear()
        self._n_docs = 0
        self._avg_doc_length = 0.0
        self._tool_summaries.clear()


# Minimal stopword list for tool search
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "this", "that", "it", "its", "as", "or", "and", "but", "if",
    "can", "will", "do", "does", "did", "has", "have", "had",
    "not", "no", "so", "up", "out", "all", "any", "each",
    "you", "your", "we", "our", "they", "them", "their",
})
