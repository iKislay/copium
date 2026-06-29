"""Tests for the MCP proxy session dedup and cache modules."""

from __future__ import annotations

from copium.mcp_proxy.cache import ProxyCache
from copium.mcp_proxy.session_dedup import SessionDedup


class TestSessionDedup:
    """Test suite for SessionDedup."""

    def setup_method(self):
        self.dedup = SessionDedup()

    def test_first_definitions_not_deduped(self):
        """First time seeing tool definitions should return None."""
        tools = [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ]
        result = self.dedup.check_definitions(tools)
        assert result is None

    def test_repeated_definitions_deduped(self):
        """Same definitions sent again should return dedup marker."""
        tools = [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ]
        self.dedup.check_definitions(tools)
        result = self.dedup.check_definitions(tools)
        assert result is not None
        assert "cached" in result

    def test_different_definitions_not_deduped(self):
        """Different tool definitions should not be deduped."""
        tools1 = [{"name": "read_file", "description": "Read a file"}]
        tools2 = [{"name": "write_file", "description": "Write a file"}]
        self.dedup.check_definitions(tools1)
        result = self.dedup.check_definitions(tools2)
        assert result is None

    def test_first_call_not_deduped(self):
        """First call to a tool should not be deduped."""
        result = self.dedup.check_call(
            "read_file", {"path": "/src/main.py"}, "file contents here"
        )
        assert result is None

    def test_repeated_call_same_result_deduped(self):
        """Same call with same result should be deduped."""
        args = {"path": "/src/main.py"}
        content = "file contents here"
        self.dedup.check_call("read_file", args, content)
        result = self.dedup.check_call("read_file", args, content)
        assert result is not None
        assert "Same as previous" in result

    def test_repeated_call_different_result_not_deduped(self):
        """Same call with different result should not be deduped."""
        args = {"path": "/src/main.py"}
        self.dedup.check_call("read_file", args, "old contents")
        result = self.dedup.check_call("read_file", args, "new contents")
        assert result is None

    def test_schema_caching(self):
        """Schema cache should store and retrieve."""
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        self.dedup.cache_schema("read_file", schema)
        assert self.dedup.has_schema("read_file")
        assert self.dedup.get_cached_schema("read_file") == schema
        assert not self.dedup.has_schema("write_file")

    def test_reset_clears_all(self):
        """Reset should clear all caches."""
        tools = [{"name": "test", "description": "test"}]
        self.dedup.check_definitions(tools)
        self.dedup.check_call("test", {}, "result")
        self.dedup.cache_schema("test", {})
        self.dedup.reset()
        assert self.dedup.stats["dedup_hits"] == 0
        assert not self.dedup.has_schema("test")

    def test_stats_tracking(self):
        """Stats should track hits and misses."""
        tools = [{"name": "test", "description": "test"}]
        self.dedup.check_definitions(tools)
        self.dedup.check_definitions(tools)
        self.dedup.check_definitions(tools)
        assert self.dedup.stats["dedup_hits"] == 2
        assert self.dedup.stats["dedup_misses"] == 1


class TestProxyCache:
    """Test suite for ProxyCache."""

    def setup_method(self):
        self.cache = ProxyCache(default_ttl=300.0)

    def test_get_miss(self):
        """Cache miss should return None."""
        assert self.cache.get("nonexistent") is None

    def test_set_and_get(self):
        """Set should store value, get should retrieve it."""
        self.cache.set("key1", "value1")
        assert self.cache.get("key1") == "value1"

    def test_invalidate(self):
        """Invalidate should remove specific key."""
        self.cache.set("key1", "value1")
        assert self.cache.invalidate("key1")
        assert self.cache.get("key1") is None

    def test_invalidate_prefix(self):
        """Invalidate prefix should remove all matching keys."""
        self.cache.set("server:fs:tools", "tools_data")
        self.cache.set("server:fs:schema", "schema_data")
        self.cache.set("server:gh:tools", "other_data")
        removed = self.cache.invalidate_prefix("server:fs:")
        assert removed == 2
        assert self.cache.get("server:fs:tools") is None
        assert self.cache.get("server:gh:tools") == "other_data"

    def test_clear(self):
        """Clear should remove all entries."""
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.clear()
        assert self.cache.size == 0

    def test_expired_entries_not_returned(self):
        """Expired entries should return None on get."""
        self.cache.set("key1", "value1", ttl=0.0)  # Immediate expiry
        # TTL=0 means already expired
        import time
        time.sleep(0.01)
        assert self.cache.get("key1") is None

    def test_stats(self):
        """Stats should track hits and misses."""
        self.cache.set("key1", "value1")
        self.cache.get("key1")  # hit
        self.cache.get("key2")  # miss
        stats = self.cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_max_entries_eviction(self):
        """Cache should evict when max entries reached."""
        small_cache = ProxyCache(default_ttl=300.0, max_entries=3)
        small_cache.set("a", 1)
        small_cache.set("b", 2)
        small_cache.set("c", 3)
        small_cache.set("d", 4)  # Should trigger eviction
        assert small_cache.size <= 3
