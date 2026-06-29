"""Orientation cache for agent sessions.

Pre-built codebase maps that let agents skip the orientation phase entirely.
Instead of 5-10 tool calls to discover project structure, Copium provides
a compressed map on the first request (~500 tokens vs 3000+ for exploration).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Key files that signal project type and structure
_KEY_FILES = [
    "package.json",
    "Cargo.toml",
    "pyproject.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "CMakeLists.txt",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    ".github/workflows",
    "tsconfig.json",
    "setup.py",
    "requirements.txt",
    "Gemfile",
]

# Directories to skip during scanning
_SKIP_DIRS = frozenset({
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "target",
    "build",
    "dist",
    ".next",
    ".nuxt",
    "vendor",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
    ".coverage",
    "htmlcov",
    "egg-info",
})


@dataclass
class ProjectInfo:
    """Detected project metadata."""

    project_type: str  # python, rust, node, go, java, etc.
    name: str
    entry_points: list[str] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    doc_dirs: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)


@dataclass
class CodebaseMap:
    """Pre-built map of a codebase for agent orientation."""

    project_root: str
    project_info: ProjectInfo
    directory_tree: dict[str, list[str]]  # path → children (top 3 levels)
    key_files: list[str]  # Important files found
    recent_changes: list[str]  # Recently modified files
    scan_time: float = 0.0
    token_estimate: int = 0
    fingerprint: str = ""  # Hash for cache invalidation

    def to_compact_text(self) -> str:
        """Render as compact text for injection into agent context.

        Target: ~500 tokens, structured for quick agent parsing.
        """
        lines = [
            f"# Project: {self.project_info.name} ({self.project_info.project_type})",
            "",
            "## Structure (top-level):",
        ]

        # Show top-level directory
        root_children = self.directory_tree.get(".", [])
        for child in sorted(root_children)[:30]:
            lines.append(f"  {child}")

        if self.project_info.entry_points:
            lines.append("")
            lines.append("## Entry Points:")
            for ep in self.project_info.entry_points[:5]:
                lines.append(f"  {ep}")

        if self.project_info.test_dirs:
            lines.append("")
            lines.append("## Tests:")
            for td in self.project_info.test_dirs[:3]:
                lines.append(f"  {td}/")

        if self.key_files:
            lines.append("")
            lines.append("## Key Config:")
            for kf in self.key_files[:10]:
                lines.append(f"  {kf}")

        if self.recent_changes:
            lines.append("")
            lines.append("## Recently Modified:")
            for rc in self.recent_changes[:5]:
                lines.append(f"  {rc}")

        text = "\n".join(lines)
        self.token_estimate = len(text) // 4
        return text

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/transport."""
        return {
            "project_root": self.project_root,
            "project_info": {
                "project_type": self.project_info.project_type,
                "name": self.project_info.name,
                "entry_points": self.project_info.entry_points,
                "test_dirs": self.project_info.test_dirs,
                "doc_dirs": self.project_info.doc_dirs,
                "config_files": self.project_info.config_files,
            },
            "directory_tree": self.directory_tree,
            "key_files": self.key_files,
            "recent_changes": self.recent_changes,
            "scan_time": self.scan_time,
            "token_estimate": self.token_estimate,
            "fingerprint": self.fingerprint,
        }


class OrientationCache:
    """Pre-built codebase maps to skip the agent orientation tax.

    Scans a project directory and builds a compact map that can be
    injected into the first agent message, replacing 5-10 tool calls
    with a single ~500-token context block.

    Example:
        >>> cache = OrientationCache()
        >>> codebase_map = cache.build_codebase_map("/path/to/project")
        >>> compact = codebase_map.to_compact_text()
        >>> len(compact) // 4  # ~500 tokens
        487
    """

    def __init__(self, max_depth: int = 3, cache_dir: str | None = None):
        """Initialize orientation cache.

        Args:
            max_depth: Maximum directory depth to scan.
            cache_dir: Directory to store cached maps. Defaults to .copium/cache/.
        """
        self._max_depth = max_depth
        self._cache_dir = cache_dir
        self._cached_maps: dict[str, CodebaseMap] = {}

    def build_codebase_map(self, project_root: str) -> CodebaseMap:
        """Scan project and build orientation map.

        Args:
            project_root: Root directory of the project.

        Returns:
            CodebaseMap with project structure, key files, and metadata.
        """
        root = Path(project_root).resolve()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {project_root}")

        start = time.time()

        # Scan directory tree
        directory_tree = self._scan_tree(root)

        # Detect key files
        key_files = self._find_key_files(root)

        # Detect project info
        project_info = self._detect_project(root, key_files)

        # Get recent changes (git-based if available)
        recent_changes = self._get_recent_changes(root)

        # Compute fingerprint for cache invalidation
        fingerprint = self._compute_fingerprint(root, key_files)

        codebase_map = CodebaseMap(
            project_root=str(root),
            project_info=project_info,
            directory_tree=directory_tree,
            key_files=key_files,
            recent_changes=recent_changes,
            scan_time=time.time() - start,
            fingerprint=fingerprint,
        )

        # Cache it
        self._cached_maps[str(root)] = codebase_map
        logger.info(
            "Built orientation cache for %s in %.2fs (%d key files)",
            root.name,
            codebase_map.scan_time,
            len(key_files),
        )

        return codebase_map

    def get_cached(self, project_root: str) -> CodebaseMap | None:
        """Get cached map if available and still valid.

        Args:
            project_root: Project root to look up.

        Returns:
            Cached CodebaseMap or None if not cached/stale.
        """
        root = str(Path(project_root).resolve())
        return self._cached_maps.get(root)

    def inject_orientation_context(
        self,
        messages: list[dict[str, Any]],
        codebase_map: CodebaseMap,
    ) -> list[dict[str, Any]]:
        """Prepend orientation context to message list.

        Injects the compact codebase map as a system message prefix,
        giving the agent immediate project awareness.

        Args:
            messages: Original message list.
            codebase_map: Pre-built codebase map.

        Returns:
            Messages with orientation context prepended.
        """
        orientation_text = codebase_map.to_compact_text()
        orientation_msg = {
            "role": "system",
            "content": (
                "[Copium Orientation Cache — pre-built project map]\n\n"
                + orientation_text
                + "\n\n[End orientation cache — agent can skip structural exploration]"
            ),
        }

        # Insert after system prompt if one exists, else prepend
        if messages and messages[0].get("role") == "system":
            return [messages[0], orientation_msg] + messages[1:]
        return [orientation_msg] + messages

    def update_incremental(
        self,
        project_root: str,
        since_time: float | None = None,
    ) -> CodebaseMap:
        """Incrementally update an existing cached map.

        Only rescans directories that have been modified since last scan.

        Args:
            project_root: Project root to update.
            since_time: Only scan files modified after this timestamp.

        Returns:
            Updated CodebaseMap.
        """
        existing = self.get_cached(project_root)
        if existing is None or since_time is None:
            return self.build_codebase_map(project_root)

        root = Path(project_root).resolve()

        # Only update recent changes and check for new key files
        recent_changes = self._get_recent_changes(root)
        new_fingerprint = self._compute_fingerprint(
            root, existing.key_files
        )

        if new_fingerprint == existing.fingerprint:
            # Nothing changed — return existing
            return existing

        # Fingerprint changed — do full rebuild
        return self.build_codebase_map(project_root)

    def _scan_tree(self, root: Path) -> dict[str, list[str]]:
        """Scan directory tree up to max_depth."""
        tree: dict[str, list[str]] = {}

        def _scan(path: Path, depth: int, rel_prefix: str) -> None:
            if depth > self._max_depth:
                return

            children = []
            try:
                entries = sorted(path.iterdir())
            except PermissionError:
                return

            for entry in entries:
                name = entry.name
                if name.startswith(".") and name != ".github":
                    continue
                if entry.is_dir():
                    if name in _SKIP_DIRS:
                        continue
                    children.append(name + "/")
                    child_rel = f"{rel_prefix}/{name}" if rel_prefix != "." else name
                    _scan(entry, depth + 1, child_rel)
                else:
                    children.append(name)

            tree[rel_prefix] = children

        _scan(root, 0, ".")
        return tree

    def _find_key_files(self, root: Path) -> list[str]:
        """Find key project files."""
        found = []
        for key_file in _KEY_FILES:
            path = root / key_file
            if path.exists():
                found.append(key_file)
        return found

    def _detect_project(self, root: Path, key_files: list[str]) -> ProjectInfo:
        """Detect project type and metadata from key files."""
        project_type = "unknown"
        name = root.name
        entry_points: list[str] = []
        test_dirs: list[str] = []
        doc_dirs: list[str] = []

        if "Cargo.toml" in key_files:
            project_type = "rust"
            if (root / "src" / "main.rs").exists():
                entry_points.append("src/main.rs")
            if (root / "src" / "lib.rs").exists():
                entry_points.append("src/lib.rs")
        elif "pyproject.toml" in key_files or "setup.py" in key_files:
            project_type = "python"
            # Look for common python entry points
            for candidate in ("main.py", "app.py", "cli.py", "__main__.py"):
                if (root / candidate).exists():
                    entry_points.append(candidate)
        elif "package.json" in key_files:
            project_type = "node"
            if (root / "src" / "index.ts").exists():
                entry_points.append("src/index.ts")
            elif (root / "src" / "index.js").exists():
                entry_points.append("src/index.js")
            elif (root / "index.js").exists():
                entry_points.append("index.js")
        elif "go.mod" in key_files:
            project_type = "go"
            if (root / "main.go").exists():
                entry_points.append("main.go")
            elif (root / "cmd").is_dir():
                entry_points.append("cmd/")

        # Detect test directories
        for test_dir in ("tests", "test", "spec", "__tests__", "e2e"):
            if (root / test_dir).is_dir():
                test_dirs.append(test_dir)

        # Detect doc directories
        for doc_dir in ("docs", "doc", "documentation", "guides"):
            if (root / doc_dir).is_dir():
                doc_dirs.append(doc_dir)

        return ProjectInfo(
            project_type=project_type,
            name=name,
            entry_points=entry_points,
            test_dirs=test_dirs,
            doc_dirs=doc_dirs,
            config_files=key_files,
        )

    def _get_recent_changes(self, root: Path) -> list[str]:
        """Get recently changed files from git log."""
        try:
            import subprocess

            result = subprocess.run(
                ["git", "log", "--oneline", "--name-only", "-10", "--pretty=format:"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                files = [
                    f.strip()
                    for f in result.stdout.strip().split("\n")
                    if f.strip()
                ]
                # Deduplicate while preserving order
                seen: set[str] = set()
                unique = []
                for f in files:
                    if f not in seen:
                        seen.add(f)
                        unique.append(f)
                return unique[:10]
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
        return []

    def _compute_fingerprint(self, root: Path, key_files: list[str]) -> str:
        """Compute a fingerprint for cache invalidation."""
        hasher = hashlib.sha256()
        for kf in sorted(key_files):
            path = root / kf
            if path.is_file():
                try:
                    stat = path.stat()
                    hasher.update(f"{kf}:{stat.st_mtime}:{stat.st_size}".encode())
                except OSError:
                    pass
        return hasher.hexdigest()[:16]
