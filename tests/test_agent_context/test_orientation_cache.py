"""Tests for agent_context orientation cache."""

import tempfile
from pathlib import Path

from copium.agent_context.orientation_cache import (
    CodebaseMap,
    OrientationCache,
)


class TestOrientationCache:
    """Test orientation cache codebase scanning."""

    def setup_method(self):
        self.cache = OrientationCache(max_depth=2)

    def test_build_codebase_map(self, tmp_path):
        # Create a minimal project structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("def test_hello(): pass")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
        (tmp_path / "README.md").write_text("# Test Project")

        codebase_map = self.cache.build_codebase_map(str(tmp_path))

        assert codebase_map.project_info.project_type == "python"
        assert "pyproject.toml" in codebase_map.key_files
        assert "tests" in codebase_map.project_info.test_dirs

    def test_compact_text_under_budget(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")

        codebase_map = self.cache.build_codebase_map(str(tmp_path))
        compact = codebase_map.to_compact_text()

        # Should be concise — well under 1000 tokens
        assert len(compact) // 4 < 1000

    def test_caching(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "test"')
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.rs").write_text("fn main() {}")

        self.cache.build_codebase_map(str(tmp_path))
        cached = self.cache.get_cached(str(tmp_path))

        assert cached is not None
        assert cached.project_info.project_type == "rust"

    def test_inject_orientation_context(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
        codebase_map = self.cache.build_codebase_map(str(tmp_path))

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What does this project do?"},
        ]

        injected = self.cache.inject_orientation_context(messages, codebase_map)

        assert len(injected) == 3  # system + orientation + user
        assert "Orientation Cache" in injected[1]["content"]

    def test_inject_without_system_message(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
        codebase_map = self.cache.build_codebase_map(str(tmp_path))

        messages = [{"role": "user", "content": "Hello"}]
        injected = self.cache.inject_orientation_context(messages, codebase_map)

        assert len(injected) == 2
        assert injected[0]["role"] == "system"

    def test_detect_node_project(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "index.ts").write_text("export default {}")

        codebase_map = self.cache.build_codebase_map(str(tmp_path))
        assert codebase_map.project_info.project_type == "node"
        assert "src/index.ts" in codebase_map.project_info.entry_points

    def test_detect_rust_project(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"')
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.rs").write_text("fn main() {}")

        codebase_map = self.cache.build_codebase_map(str(tmp_path))
        assert codebase_map.project_info.project_type == "rust"
        assert "src/main.rs" in codebase_map.project_info.entry_points

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "express").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.js").write_text("")

        codebase_map = self.cache.build_codebase_map(str(tmp_path))
        # node_modules should not appear in tree
        all_dirs = []
        for children in codebase_map.directory_tree.values():
            all_dirs.extend(children)
        assert "node_modules/" not in all_dirs

    def test_to_dict_roundtrip(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
        codebase_map = self.cache.build_codebase_map(str(tmp_path))
        data = codebase_map.to_dict()

        assert data["project_info"]["project_type"] == "python"
        assert "pyproject.toml" in data["key_files"]

    def test_invalid_directory_raises(self):
        try:
            self.cache.build_codebase_map("/nonexistent/path/xyz")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
