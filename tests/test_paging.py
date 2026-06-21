"""Tests for cold/hot context paging."""

from __future__ import annotations

import tempfile

import pytest

from copium.paging import (
    EvictionPolicy,
    Page,
    PageFault,
    PageStatus,
    PageStore,
    PagingConfig,
    PagingManager,
)


class TestPage:
    """Test Page dataclass."""

    def test_basic_page(self):
        page = Page(
            page_id="abc123",
            content="test content",
            role="tool",
            turn_index=0,
            token_count=10,
        )
        assert page.status == PageStatus.HOT
        assert not page.pinned

    def test_touch(self):
        page = Page(
            page_id="abc123",
            content="test",
            role="tool",
            turn_index=0,
            token_count=10,
        )
        page.touch()
        assert page.access_count == 1
        page.touch()
        assert page.access_count == 2

    def test_to_marker(self):
        page = Page(
            page_id="abc123def456",
            content="test content",
            role="tool",
            turn_index=3,
            token_count=10,
        )
        marker = page.to_marker()
        assert "CONTEXT-PAGE-abc123de" in marker
        assert "role=tool" in marker
        assert "turn=3" in marker
        assert "memory_fault" in marker


class TestPageStore:
    """Test SQLite page store."""

    def _make_store(self, path=None):
        config = PagingConfig(store_path=path)
        return PageStore(config)

    def test_store_and_retrieve(self):
        store = self._make_store()
        page = Page(
            page_id="test123",
            content="hello world",
            role="tool",
            turn_index=0,
            token_count=5,
        )
        store.store_page(page)
        retrieved = store.retrieve_page("test123")
        assert retrieved is not None
        assert retrieved.content == "hello world"
        assert retrieved.role == "tool"
        store.close()

    def test_retrieve_nonexistent(self):
        store = self._make_store()
        assert store.retrieve_page("nonexistent") is None
        store.close()

    def test_remove_page(self):
        store = self._make_store()
        page = Page(
            page_id="test123",
            content="hello",
            role="tool",
            turn_index=0,
            token_count=5,
        )
        store.store_page(page)
        store.remove_page("test123")
        assert store.retrieve_page("test123") is None
        store.close()

    def test_fifo_eviction_candidates(self):
        config = PagingConfig(eviction_policy="fifo", eviction_tau=2)
        store = PageStore(config)

        # Add pages from turns 0, 1, 2, 3
        for turn in range(4):
            page = Page(
                page_id=f"page{turn}",
                content=f"content{turn}",
                role="tool",
                turn_index=turn,
                token_count=10,
            )
            store.store_page(page)

        # τ=2: keep last 2 turns. At turn 3, cutoff=1 → only turn 0 is evictable
        candidates = store.get_eviction_candidates(current_turn=3)
        assert len(candidates) == 1
        assert candidates[0].turn_index == 0
        store.close()

    def test_pinned_not_evicted(self):
        config = PagingConfig(eviction_policy="fifo", eviction_tau=1)
        store = PageStore(config)

        # Add a pinned page from turn 0
        page = Page(
            page_id="pinned1",
            content="important",
            role="tool",
            turn_index=0,
            token_count=10,
            pinned=True,
        )
        store.store_page(page)

        # Add a non-pinned page from turn 0
        page2 = Page(
            page_id="normal1",
            content="normal",
            role="tool",
            turn_index=0,
            token_count=10,
        )
        store.store_page(page2)

        candidates = store.get_eviction_candidates(current_turn=2)
        # Only normal1 should be a candidate (pinned1 is excluded)
        assert len(candidates) == 1
        assert candidates[0].page_id == "normal1"
        store.close()

    def test_record_fault(self):
        store = self._make_store()
        store.record_fault("page1", turn_index=5, hint="test hint")
        count = store.get_fault_count("page1")
        assert count == 1
        store.close()

    def test_file_backed_store(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            store = self._make_store(path=f.name)
            page = Page(
                page_id="persistent",
                content="saved to disk",
                role="tool",
                turn_index=0,
                token_count=5,
            )
            store.store_page(page)
            store.close()

            # Reopen and verify
            store2 = self._make_store(path=f.name)
            retrieved = store2.retrieve_page("persistent")
            assert retrieved is not None
            assert retrieved.content == "saved to disk"
            store2.close()


class TestPagingManager:
    """Test PagingManager."""

    def _make_manager(self, **config_kwargs):
        config = PagingConfig(**config_kwargs)
        return PagingManager(config)

    def test_register_page(self):
        manager = self._make_manager()
        page_id = manager.register_page("test content", "tool", 10)
        assert page_id
        assert len(page_id) == 16  # SHA-256 truncated
        stats = manager.get_stats()
        assert stats["hot_pages"] == 1
        manager.close()

    def test_duplicate_registration(self):
        manager = self._make_manager()
        id1 = manager.register_page("same content", "tool", 10)
        id2 = manager.register_page("same content", "tool", 10)
        assert id1 == id2  # Same content → same page_id
        stats = manager.get_stats()
        assert stats["hot_pages"] == 1  # Not duplicated
        manager.close()

    def test_advance_turn(self):
        manager = self._make_manager()
        assert manager._current_turn == 0
        manager.advance_turn()
        assert manager._current_turn == 1
        manager.close()

    def test_eviction_fifo(self):
        manager = self._make_manager(eviction_policy="fifo", eviction_tau=1)

        # Register pages in turns 0, 1, 2, 3
        for turn in range(4):
            manager.register_page(f"content{turn}", "tool", 100)
            manager.advance_turn()

        # Current turn is 4, τ=1 → pages from turns 0, 1, 2 are evictable
        # (turn_index < 4-1 = 3)
        manager.config.hot_context_budget = 0.1  # Very low budget
        evicted, freed = manager.evict_cold_content(token_budget=10)
        assert len(evicted) > 0
        assert freed > 0
        manager.close()

    def test_no_eviction_when_under_budget(self):
        manager = self._make_manager()
        manager.register_page("content", "tool", 100)
        manager.advance_turn()

        # High budget → no eviction
        evicted, freed = manager.evict_cold_content(token_budget=100000)
        assert len(evicted) == 0
        assert freed == 0
        manager.close()

    def test_page_fault(self):
        manager = self._make_manager(eviction_policy="fifo", eviction_tau=1)

        # Register a page and advance turns
        page_id = manager.register_page("important content", "tool", 100)
        manager.advance_turn()
        manager.advance_turn()
        manager.advance_turn()

        # Force eviction: τ=1, current_turn=3 → cutoff=2 → page at turn 0 is evictable
        manager.config.hot_context_budget = 0.0
        evicted, _ = manager.evict_cold_content(token_budget=0)
        assert len(evicted) > 0, f"Expected evictions, got {evicted}"

        # Verify it's cold
        page = manager._pages[page_id]
        assert page.status == PageStatus.COLD

        # Trigger fault
        faulted_page = manager.handle_fault(page_id[:8])
        assert faulted_page is not None
        assert faulted_page.status == PageStatus.HOT
        assert faulted_page.pinned  # Auto-pinned after fault
        manager.close()

    def test_pin_page(self):
        manager = self._make_manager()
        page_id = manager.register_page("content", "tool", 100)
        result = manager.pin_page(page_id[:8], reason="user_bookmark")
        assert result is True
        page = manager._pages[page_id]
        assert page.pinned
        assert page.pin_reason == "user_bookmark"
        manager.close()

    def test_stats(self):
        manager = self._make_manager()
        manager.register_page("content1", "tool", 100)
        manager.register_page("content2", "tool", 200)
        stats = manager.get_stats()
        assert stats["hot_pages"] == 2
        assert stats["hot_tokens"] == 300
        assert stats["total_pages"] == 2
        assert stats["evictions"] == 0
        assert stats["faults"] == 0
        manager.close()

    def test_disabled_config(self):
        config = PagingConfig(enabled=False)
        manager = PagingManager(config)
        manager.register_page("content", "tool", 100)
        manager.advance_turn()
        evicted, freed = manager.evict_cold_content(token_budget=0)
        assert len(evicted) == 0
        manager.close()


class TestPagingTransform:
    """Test PagingTransform in the pipeline."""

    def _run_transform(self, messages, config=None):
        from copium.tokenizers import get_tokenizer
        from copium.tokenizer import Tokenizer
        from copium.transforms.paging_transform import PagingTransform

        tc = get_tokenizer("gpt-4")
        tokenizer = Tokenizer(tc, "gpt-4")
        paging_config = config or PagingConfig()
        transform = PagingTransform(paging_config)
        return transform.apply(messages, tokenizer)

    def test_tool_outputs_registered(self):
        messages = [
            {"role": "user", "content": "Run tests"},
            {"role": "tool", "content": "test output " * 20},
        ]
        result = self._run_transform(messages)
        # Messages should be preserved
        assert len(result.messages) == 2
        assert result.messages[0]["content"] == "Run tests"

    def test_user_messages_not_paged(self):
        messages = [
            {"role": "user", "content": "user message " * 20},
            {"role": "assistant", "content": "assistant response " * 20},
        ]
        result = self._run_transform(messages)
        # User/assistant messages should not be registered as pages
        assert result.messages[0]["role"] == "user"
        assert result.messages[1]["role"] == "assistant"

    def test_disabled_config(self):
        from copium.transforms.paging_transform import PagingTransform

        config = PagingConfig(enabled=False)
        messages = [
            {"role": "user", "content": "test"},
            {"role": "tool", "content": "output " * 20},
        ]
        result = self._run_transform(messages, config)
        assert not result.transforms_applied

    def test_tokens_not_inflated(self):
        messages = [
            {"role": "user", "content": "Run tests"},
            {"role": "tool", "content": "test output " * 20},
        ]
        result = self._run_transform(messages)
        # Token count should not increase
        assert result.tokens_after <= result.tokens_before
