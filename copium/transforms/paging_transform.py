"""Paging transform for cold/hot context management.

Integrates the PagingManager into the compression pipeline. After
ContentRouter compresses tool outputs, this transform:
1. Registers each tool output as a page
2. Evicts old pages when context exceeds budget
3. Replaces evicted content with retrieval markers
4. Handles page faults when the model references evicted content
"""

from __future__ import annotations

from typing import Any

from ..config import TransformResult
from ..paging import PagingConfig, PagingManager, PageStatus
from ..tokenizer import Tokenizer
from .base import Transform


class PagingTransform(Transform):
    """Manages cold/hot context paging in the pipeline.

    After ContentRouter compresses tool outputs, this transform
    registers them as pages and evicts old content when the context
    exceeds the budget. Evicted content is replaced with retrieval
    markers that can trigger page faults.
    """

    name = "context_pager"

    def __init__(self, config: PagingConfig | None = None):
        self.config = config or PagingConfig()
        self.manager = PagingManager(self.config)

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Apply cold/hot context paging.

        Registers tool outputs as pages, evicts cold content, and
        replaces evicted content with retrieval markers.
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

        # Calculate token budget for hot context
        budget_tokens = int(tokens_before * self.config.hot_context_budget)

        result_messages: list[dict[str, Any]] = []
        transforms_applied: list[str] = []
        pages_registered = 0
        pages_evicted = 0

        for i, msg in enumerate(messages):
            if i < frozen_count:
                result_messages.append(msg)
                continue

            role = msg.get("role", "")
            content = msg.get("content", "")

            if not isinstance(content, str):
                result_messages.append(msg)
                continue

            # Register tool outputs as pages
            if role in ("tool", "tool_result", "function") and len(content) > 50:
                page_id = self.manager.register_page(
                    content, role, tokenizer.count_text(content)
                )
                pages_registered += 1

                # Check if this page should be evicted
                # (will be handled in the eviction pass below)
                result_messages.append(msg)
            else:
                result_messages.append(msg)

        # Advance the turn
        self.manager.advance_turn()

        # Evict cold content if over budget
        evicted_ids, freed_tokens = self.manager.evict_cold_content(budget_tokens)

        if evicted_ids:
            # Replace evicted content with markers
            for i, msg in enumerate(result_messages):
                if i < frozen_count:
                    continue

                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue

                # Check if this content matches an evicted page
                for page_id in evicted_ids:
                    page = self.manager._pages.get(page_id)
                    if page and page.content == content:
                        # Replace with marker
                        new_msg = dict(msg)
                        new_msg["content"] = page.to_marker()
                        result_messages[i] = new_msg
                        pages_evicted += 1
                        break

            transforms_applied.append(
                f"paging:evict:{pages_evicted}:{freed_tokens}"
            )

        # Calculate final tokens
        tokens_after = tokenizer.count_messages(result_messages)

        # Log stats
        stats = self.manager.get_stats()
        if pages_evicted > 0:
            import logging

            logger = logging.getLogger(__name__)
            logger.info(
                "Paging: %d pages registered, %d evicted (%d tokens freed), "
                "%d hot, %d cold, fault_rate=%.4f",
                pages_registered,
                pages_evicted,
                freed_tokens,
                stats["hot_pages"],
                stats["cold_pages"],
                stats["fault_rate"],
            )

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=transforms_applied,
        )
