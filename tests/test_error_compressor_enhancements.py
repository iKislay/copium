"""Tests for error compressor enhancements (build grouping, Docker, compiler normalization)."""

from __future__ import annotations

from copium.transforms.error_compressor import (
    _group_build_errors,
    _compress_docker_build,
    _normalize_compiler_errors,
)


class TestGroupBuildErrors:
    """Tests for build error grouping."""

    def test_groups_typescript_errors(self):
        text = """src/a.ts: error TS2322: Type 'string' is not assignable to type 'number'
src/b.ts: error TS2322: Type 'string' is not assignable to type 'number'
src/c.ts: error TS2322: Type 'string' is not assignable to type 'number'
"""
        result = _group_build_errors(text)
        assert "3 files" in result
        assert "error TS2322" in result

    def test_groups_rust_errors(self):
        text = """src/main.rs: error[E0308]: mismatched types
src/lib.rs: error[E0308]: mismatched types
"""
        result = _group_build_errors(text)
        assert "2 files" in result

    def test_no_grouping_for_single_error(self):
        text = "src/a.ts: error TS2322: Type mismatch
"
        result = _group_build_errors(text)
        # Should not add grouping for single error
        assert "files" not in result

    def test_preserves_different_errors(self):
        text = """src/a.ts: error TS2322: Type mismatch
src/b.ts: error TS2345: Argument mismatch
"""
        result = _group_build_errors(text)
        # Different errors should not be grouped
        assert "2 files" not in result


class TestCompressDockerBuild:
    """Tests for Docker build compression."""

    def test_removes_download_progress(self):
        text = """#5 [build 1/5] RUN apt-get update
Downloading
Extracting
Pull complete
#6 [build 2/5] RUN pip install
"""
        result = _compress_docker_build(text)
        assert "Downloading" not in result
        assert "Extracting" not in result
        assert "Pull complete" not in result
        assert "RUN apt-get" in result
        assert "download/progress lines removed" in result

    def test_preserves_error_lines(self):
        text = """#5 [build 1/5] RUN make
error: compilation failed
Downloading
"""
        result = _compress_docker_build(text)
        assert "error: compilation failed" in result

    def test_no_changes_without_docker(self):
        text = "just normal text
nothing docker here
"
        result = _compress_docker_build(text)
        assert "removed" not in result


class TestNormalizeCompilerErrors:
    """Tests for compiler error normalization."""

    def test_normalizes_absolute_paths(self):
        text = "/home/user/project/src/file.ts:10:5: error: type mismatch"
        result = _normalize_compiler_errors(text)
        assert "/home/user/project/" not in result
        assert "src/file.ts" in result

    def test_removes_timestamps(self):
        text = "[2026-06-28T10:30:00Z] error: build failed"
        result = _normalize_compiler_errors(text)
        assert "2026-06-28" not in result
        assert "error: build failed" in result

    def test_collapses_repeated_warnings(self):
        text = """src/a.ts:1:1: warning: unused variable
src/b.ts:2:1: warning: unused variable
src/c.ts:3:1: warning: unused variable
src/d.ts:4:1: warning: unused variable
"""
        result = _normalize_compiler_errors(text)
        assert "repeated warning" in result

    def test_preserves_error_lines(self):
        text = "src/main.rs:10:5: error: cannot find value"
        result = _normalize_compiler_errors(text)
        assert "cannot find value" in result
