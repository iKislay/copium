"""Git-Aware File Prioritization — ranks files by VCS history signals.

When a coding agent ingests a codebase, not all files are equally important.
This module uses git history signals to rank files by importance:
- Commit frequency (files changed often matter more)
- Recency (recently changed files are more relevant)
- Author match (files authored by the current user)
- Branch relevance (files changed on the current branch)
- Dependency centrality (files imported by many others)

Multi-signal scoring:
  Priority = 0.30 * commit_frequency
           + 0.20 * recency
           + 0.10 * author_match
           + 0.10 * branch_relevance
           + 0.15 * file_type
           + 0.15 * dependency_centrality
"""

from __future__ import annotations

import math
import os
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GitPrioritizationConfig:
    """Configuration for git-aware file prioritization."""

    enabled: bool = True

    # Signal weights (must sum to 1.0)
    weight_commit_frequency: float = 0.30
    weight_recency: float = 0.20
    weight_author_match: float = 0.10
    weight_branch_relevance: float = 0.10
    weight_file_type: float = 0.15
    weight_dependency_centrality: float = 0.15

    # Recency half-life in days (files changed within this period get high score)
    recency_half_life_days: int = 90

    # Max number of commits to analyze (performance guard)
    max_commits_to_analyze: int = 5000

    # Max days back to analyze
    max_days_back: int = 365

    # File types considered "high priority" (source code)
    high_priority_extensions: frozenset[str] = frozenset(
        {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go",
            ".java", ".kt", ".swift", ".c", ".cpp", ".h",
            ".rb", ".php", ".cs", ".scala", ".clj",
        }
    )

    # File types to deprioritize
    low_priority_extensions: frozenset[str] = frozenset(
        {
            ".lock", ".min.js", ".min.css", ".map",
            ".pyc", ".pyo", ".so", ".dylib", ".dll",
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
            ".woff", ".woff2", ".ttf", ".eot",
        }
    )


def _run_git(args: list[str], cwd: Path | None = None) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(cwd) if cwd else None,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _get_current_user(cwd: Path | None = None) -> str | None:
    """Get the current git user name or email."""
    name = _run_git(["config", "user.name"], cwd=cwd)
    if name:
        return name.strip()
    email = _run_git(["config", "user.email"], cwd=cwd)
    if email:
        return email.strip()
    return None


def _get_current_branch(cwd: Path | None = None) -> str | None:
    """Get the current git branch name."""
    output = _run_git(["branch", "--show-current"], cwd=cwd)
    return output.strip() if output else None


def _get_commit_log(
    cwd: Path | None = None,
    max_commits: int = 5000,
    max_days: int = 365,
) -> list[dict[str, Any]]:
    """Get commit log with file changes."""
    since_date = f"--since={max_days} days ago"
    format_str = "--format=%H|%an|%ae|%at|%s"

    output = _run_git(
        ["log", since_date, format_str, f"-{max_commits}", "--name-only"],
        cwd=cwd,
    )
    if not output:
        return []

    commits: list[dict[str, Any]] = []
    current_commit: dict[str, Any] | None = None

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # Commit header line: hash|name|email|timestamp|subject
        parts = line.split("|", 4)
        if len(parts) == 5 and len(parts[0]) == 40:
            if current_commit:
                commits.append(current_commit)
            current_commit = {
                "hash": parts[0],
                "author_name": parts[1],
                "author_email": parts[2],
                "timestamp": int(parts[3]) if parts[3].isdigit() else 0,
                "subject": parts[4],
                "files": [],
            }
        elif current_commit is not None:
            # File change line
            current_commit["files"].append(line)

    if current_commit:
        commits.append(current_commit)

    return commits


def _get_branch_files(cwd: Path | None = None) -> set[str]:
    """Get files changed on the current branch vs main/master."""
    branch = _get_current_branch(cwd)
    if not branch:
        return set()

    # Try main first, then master
    for base in ("main", "master"):
        output = _run_git(["diff", "--name-only", f"{base}...{branch}"], cwd=cwd)
        if output:
            return set(output.splitlines())

    return set()


def _compute_file_dependencies(cwd: Path | None = None) -> dict[str, int]:
    """Compute import/dependency centrality for source files.

    Returns a dict mapping file paths to their "centrality" score
    (number of times they're imported by other files).
    """
    # Use grep to find import statements
    import_patterns = [
        r"^import\s+",
        r"^from\s+\S+\s+import",
        r'^require\s*\(',
        r'^import\s+.*from\s+',
    ]

    centrality: Counter[str] = Counter()
    for pattern in import_patterns:
        output = _run_git(
            ["grep", "-l", "--perl-regexp", pattern, "--", "*.py", "*.js", "*.ts", "*.go", "*.rs"],
            cwd=cwd,
        )
        if output:
            for source_file in output.splitlines():
                source_file = source_file.strip()
                if not source_file:
                    continue
                # This file imports things — increment centrality of the source
                centrality[source_file] += 1

    return dict(centrality)


def prioritize_files(
    paths: list[str] | None = None,
    repo_root: Path | None = None,
    config: GitPrioritizationConfig | None = None,
) -> list[tuple[str, float, dict[str, float]]]:
    """Rank files by git history importance.

    Args:
        paths: Optional list of file paths to prioritize.
               If None, uses all tracked files.
        repo_root: Repository root path. Auto-detected if None.
        config: Configuration.

    Returns:
        List of (path, total_score, signal_scores) sorted by score descending.
        signal_scores is a dict with individual signal values.
    """
    config = config or GitPrioritizationConfig()
    if not config.enabled:
        return []

    # Auto-detect repo root
    if repo_root is None:
        output = _run_git(["rev-parse", "--show-toplevel"])
        if not output:
            return []
        repo_root = Path(output.strip())

    cwd = repo_root

    # Get tracked files if no paths provided
    if paths is None:
        output = _run_git(["ls-files"], cwd=cwd)
        if not output:
            return []
        paths = [p.strip() for p in output.splitlines() if p.strip()]

    if not paths:
        return []

    # Gather signals
    now = time.time()
    current_user = _get_current_user(cwd)
    branch_files = _get_branch_files(cwd)

    # Analyze commits
    commits = _get_commit_log(
        cwd=cwd,
        max_commits=config.max_commits_to_analyze,
        max_days=config.max_days_back,
    )

    # Build per-file signals
    file_commit_counts: Counter[str] = Counter()
    file_latest_commit: dict[str, float] = {}
    file_authors: dict[str, Counter[str]] = {}

    for commit in commits:
        ts = commit["timestamp"]
        author = commit["author_name"]
        for f in commit["files"]:
            file_commit_counts[f] += 1
            if f not in file_latest_commit or ts > file_latest_commit[f]:
                file_latest_commit[f] = ts
            if f not in file_authors:
                file_authors[f] = Counter()
            file_authors[f][author] += 1

    # Compute dependency centrality
    centrality = _compute_file_dependencies(cwd)

    # Normalize signals
    max_commits = max(file_commit_counts.values()) if file_commit_counts else 1
    max_centrality = max(centrality.values()) if centrality else 1

    # Score each file
    results: list[tuple[str, float, dict[str, float]]] = []

    for path in paths:
        # Signal 1: Commit frequency
        commit_count = file_commit_counts.get(path, 0)
        freq_score = commit_count / max_commits if max_commits > 0 else 0

        # Signal 2: Recency (exponential decay)
        latest_ts = file_latest_commit.get(path, 0)
        if latest_ts > 0:
            days_ago = (now - latest_ts) / 86400
            recency_score = math.exp(-0.693 * days_ago / config.recency_half_life_days)
        else:
            recency_score = 0.0

        # Signal 3: Author match
        author_score = 0.0
        if current_user and path in file_authors:
            author_count = file_authors[path].get(current_user, 0)
            total_author_count = sum(file_authors[path].values())
            if total_author_count > 0:
                author_score = author_count / total_author_count

        # Signal 4: Branch relevance
        branch_score = 1.0 if path in branch_files else 0.0

        # Signal 5: File type priority
        ext = Path(path).suffix.lower()
        if ext in config.high_priority_extensions:
            type_score = 1.0
        elif ext in config.low_priority_extensions:
            type_score = 0.0
        else:
            type_score = 0.5

        # Signal 6: Dependency centrality
        cent = centrality.get(path, 0)
        dep_score = cent / max_centrality if max_centrality > 0 else 0

        # Weighted total
        total = (
            config.weight_commit_frequency * freq_score
            + config.weight_recency * recency_score
            + config.weight_author_match * author_score
            + config.weight_branch_relevance * branch_score
            + config.weight_file_type * type_score
            + config.weight_dependency_centrality * dep_score
        )

        signals = {
            "commit_frequency": round(freq_score, 3),
            "recency": round(recency_score, 3),
            "author_match": round(author_score, 3),
            "branch_relevance": round(branch_score, 3),
            "file_type": round(type_score, 3),
            "dependency_centrality": round(dep_score, 3),
        }

        results.append((path, round(total, 4), signals))

    # Sort by total score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results
