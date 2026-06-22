"""TF-IDF Schema Optimizer — relevance-based tool pruning.

Scores each tool definition against the current conversation context using
TF-IDF, then keeps only the top-N most relevant tools. This is a large win
for agents with 50+ tools, where most tools are irrelevant to the current turn.

Design:
  - Zero ML dependencies: uses pure-Python TF-IDF (no sentence-transformers)
  - Opt-in: disabled by default (requires corpus-level scoring to be useful)
  - Works on both OpenAI (tools[].function) and Anthropic (tools[].input_schema)
  - Returns the original tool list when fewer tools than max_tools

Example usage::

    from copium.transforms.schema_optimizer import TFIDFSchemaOptimizer

    optimizer = TFIDFSchemaOptimizer(max_tools=10)
    pruned_tools, kept, total = optimizer.prune(tools, conversation_context)
    # kept = number of tools kept; total = original tool count
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SchemaOptimizerConfig:
    """Configuration for the TF-IDF schema optimizer."""

    enabled: bool = False  # Opt-in — requires enough tools to be useful

    # Keep the top N most relevant tools
    max_tools: int = 10

    # Minimum tools before pruning kicks in (no-op for small tool sets)
    min_tools_to_optimize: int = 12

    # Minimum TF-IDF relevance score to keep a tool (0.0 = keep all ranked)
    min_relevance_score: float = 0.0

    # Always keep these tool names regardless of relevance score
    always_keep: list[str] = field(default_factory=list)

    # Tokenization: include function names, param names in the tool "document"
    include_param_names: bool = True
    include_param_descriptions: bool = True
    include_function_name: bool = True


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, splitting on non-alphanumeric chars."""
    if not text:
        return []
    # Split on non-alphanumeric, underscore, or hyphen
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text.lower())
    # Also split snake_case / camelCase into sub-tokens for better coverage
    expanded: list[str] = []
    for t in tokens:
        # Split snake_case
        parts = t.split("_")
        expanded.extend(parts)
        # Split camelCase
        camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", t)
        if len(camel_parts) > 1:
            expanded.extend(p.lower() for p in camel_parts)
    return [t for t in expanded if len(t) > 1]  # drop single chars


def _tool_to_text(tool: dict[str, Any], config: SchemaOptimizerConfig) -> str:
    """Serialize a tool definition to a flat text for TF-IDF indexing."""
    parts: list[str] = []

    # OpenAI format: {type: "function", function: {name, description, parameters}}
    func = tool.get("function", {})
    if func:
        if config.include_function_name and "name" in func:
            parts.append(func["name"])
        if "description" in func:
            parts.append(str(func.get("description", "")))
        if config.include_param_names or config.include_param_descriptions:
            params = func.get("parameters", {})
            props = params.get("properties", {})
            for pname, pschema in props.items():
                if config.include_param_names:
                    parts.append(pname)
                if config.include_param_descriptions and isinstance(pschema, dict):
                    parts.append(str(pschema.get("description", "")))

    # Anthropic format: {name, description, input_schema}
    if "name" in tool and "function" not in tool:
        if config.include_function_name:
            parts.append(tool["name"])
        if "description" in tool:
            parts.append(str(tool.get("description", "")))
        input_schema = tool.get("input_schema", {})
        if isinstance(input_schema, dict):
            props = input_schema.get("properties", {})
            for pname, pschema in props.items():
                if config.include_param_names:
                    parts.append(pname)
                if config.include_param_descriptions and isinstance(pschema, dict):
                    parts.append(str(pschema.get("description", "")))

    return " ".join(parts)


def _tool_name(tool: dict[str, Any]) -> str:
    """Extract the tool name for display/tracking."""
    func = tool.get("function", {})
    if func and "name" in func:
        return str(func["name"])
    if "name" in tool:
        return str(tool["name"])
    return "(unnamed)"


def _build_tfidf(
    documents: list[list[str]],
    query_tokens: list[str],
) -> list[float]:
    """Compute TF-IDF-based relevance scores for each document against the query.

    Uses the standard BM25-style IDF with a TF weight (term frequency in doc).

    Args:
        documents: List of token lists (one per tool).
        query_tokens: Tokens extracted from the conversation context.

    Returns:
        List of relevance scores (one per document), same length as ``documents``.
    """
    n_docs = len(documents)
    if n_docs == 0 or not query_tokens:
        return [0.0] * n_docs

    # Count document frequency for each query term
    query_set = set(query_tokens)
    doc_freq: Counter[str] = Counter()
    for doc_tokens in documents:
        for term in set(doc_tokens):
            if term in query_set:
                doc_freq[term] += 1

    query_tf = Counter(query_tokens)
    scores = []
    for doc_tokens in documents:
        doc_tf = Counter(doc_tokens)
        score = 0.0
        for term, qtf in query_tf.items():
            if term not in doc_tf:
                continue
            # TF: normalized term frequency in document
            tf = doc_tf[term] / max(len(doc_tokens), 1)
            # IDF: log((N+1) / (df+1)) — smoothed to avoid division by zero
            idf = math.log((n_docs + 1) / (doc_freq.get(term, 0) + 1)) + 1.0
            # Query weight by query TF (rare query terms count more)
            score += tf * idf * qtf
        scores.append(score)

    return scores


class TFIDFSchemaOptimizer:
    """Prune tool lists to the N most relevant tools for the current turn.

    Uses pure-Python TF-IDF — no ML models, no external dependencies.

    Usage::

        optimizer = TFIDFSchemaOptimizer(max_tools=10)
        pruned, kept, total = optimizer.prune(tools, context)
    """

    def __init__(self, config: SchemaOptimizerConfig | None = None) -> None:
        self.config = config or SchemaOptimizerConfig()

    def prune(
        self,
        tools: list[dict[str, Any]],
        context: str,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Prune tools to the top-N most relevant for ``context``.

        Args:
            tools: Original tool list (OpenAI or Anthropic format).
            context: Conversation context text (system + recent messages).

        Returns:
            (pruned_tools, n_kept, n_total) where n_total = len(tools).
        """
        config = self.config
        n_total = len(tools)

        if not config.enabled or n_total <= config.min_tools_to_optimize:
            return tools, n_total, n_total

        # Build per-tool documents
        tool_texts = [_tool_to_text(t, config) for t in tools]
        tool_docs = [_tokenize(text) for text in tool_texts]
        query_tokens = _tokenize(context)

        if not query_tokens:
            # No context to score against — return top max_tools unchanged
            return tools[: config.max_tools], config.max_tools, n_total

        scores = _build_tfidf(tool_docs, query_tokens)

        # Build (score, index) pairs; always-keep tools get max score
        always_keep_names = set(config.always_keep)
        ranked: list[tuple[float, int]] = []
        pinned: list[int] = []
        for i, (tool, score) in enumerate(zip(tools, scores)):
            name = _tool_name(tool)
            if name in always_keep_names:
                pinned.append(i)
            else:
                ranked.append((score, i))

        # Sort descending by score, then keep top N minus always-kept
        ranked.sort(reverse=True)
        slots_remaining = max(0, config.max_tools - len(pinned))
        selected_indices = pinned + [
            idx
            for score, idx in ranked[:slots_remaining]
            if score >= config.min_relevance_score
        ]

        if len(selected_indices) >= n_total:
            # All tools passed the threshold — no pruning needed
            return tools, n_total, n_total

        # Preserve original tool order
        keep_set = set(selected_indices)
        pruned = [tool for i, tool in enumerate(tools) if i in keep_set]
        return pruned, len(pruned), n_total

    def score_tools(
        self,
        tools: list[dict[str, Any]],
        context: str,
    ) -> list[tuple[str, float]]:
        """Return (tool_name, relevance_score) pairs for inspection/debugging.

        Args:
            tools: Tool list (OpenAI or Anthropic format).
            context: Conversation context text.

        Returns:
            List of (name, score) sorted by score descending.
        """
        tool_texts = [_tool_to_text(t, self.config) for t in tools]
        tool_docs = [_tokenize(text) for text in tool_texts]
        query_tokens = _tokenize(context)
        scores = _build_tfidf(tool_docs, query_tokens)
        named = [(_tool_name(t), s) for t, s in zip(tools, scores)]
        named.sort(key=lambda x: x[1], reverse=True)
        return named
