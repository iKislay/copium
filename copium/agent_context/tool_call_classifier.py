"""Tool call classifier for agent context management.

Classifies tool calls by their type and compressibility, enabling
the compression scheduler to apply content-type-specific strategies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ToolCallType(Enum):
    """Classification of tool call types by content category."""

    DIRECTORY_LISTING = "directory_listing"
    FILE_READ = "file_read"
    GREP_SEARCH = "grep_search"
    FILE_WRITE = "file_write"
    COMMAND_EXECUTION = "command_execution"
    TEST_RUN = "test_run"
    GIT_OPERATION = "git_operation"
    CONFIG_READ = "config_read"
    DOCUMENTATION = "documentation"
    ERROR_OUTPUT = "error_output"
    JSON_DATA = "json_data"
    SCHEMA_DEFINITION = "schema_definition"
    UNKNOWN = "unknown"


# Compressibility ratings per tool call type (0.0 = incompressible, 1.0 = highly compressible)
COMPRESSIBILITY: dict[ToolCallType, float] = {
    ToolCallType.DIRECTORY_LISTING: 0.90,
    ToolCallType.FILE_READ: 0.10,
    ToolCallType.GREP_SEARCH: 0.85,
    ToolCallType.FILE_WRITE: 0.05,
    ToolCallType.COMMAND_EXECUTION: 0.70,
    ToolCallType.TEST_RUN: 0.80,
    ToolCallType.GIT_OPERATION: 0.75,
    ToolCallType.CONFIG_READ: 0.10,
    ToolCallType.DOCUMENTATION: 0.30,
    ToolCallType.ERROR_OUTPUT: 0.65,
    ToolCallType.JSON_DATA: 0.40,
    ToolCallType.SCHEMA_DEFINITION: 0.55,
    ToolCallType.UNKNOWN: 0.50,
}

# Value scores — how important the content is to preserve accurately
VALUE_SCORES: dict[ToolCallType, float] = {
    ToolCallType.DIRECTORY_LISTING: 0.15,
    ToolCallType.FILE_READ: 0.90,
    ToolCallType.GREP_SEARCH: 0.50,
    ToolCallType.FILE_WRITE: 0.95,
    ToolCallType.COMMAND_EXECUTION: 0.60,
    ToolCallType.TEST_RUN: 0.70,
    ToolCallType.GIT_OPERATION: 0.55,
    ToolCallType.CONFIG_READ: 0.80,
    ToolCallType.DOCUMENTATION: 0.40,
    ToolCallType.ERROR_OUTPUT: 0.85,
    ToolCallType.JSON_DATA: 0.45,
    ToolCallType.SCHEMA_DEFINITION: 0.50,
    ToolCallType.UNKNOWN: 0.50,
}


# Tool name → type mappings
_TOOL_TYPE_MAP: dict[str, ToolCallType] = {
    # Directory operations
    "list_dir": ToolCallType.DIRECTORY_LISTING,
    "list_directory": ToolCallType.DIRECTORY_LISTING,
    "ls": ToolCallType.DIRECTORY_LISTING,
    "tree": ToolCallType.DIRECTORY_LISTING,
    "find": ToolCallType.DIRECTORY_LISTING,
    "get_workspace_structure": ToolCallType.DIRECTORY_LISTING,
    # File reads
    "read_file": ToolCallType.FILE_READ,
    "cat": ToolCallType.FILE_READ,
    "head": ToolCallType.FILE_READ,
    "tail": ToolCallType.FILE_READ,
    "view_source": ToolCallType.FILE_READ,
    # Search operations
    "grep": ToolCallType.GREP_SEARCH,
    "grep_search": ToolCallType.GREP_SEARCH,
    "rg": ToolCallType.GREP_SEARCH,
    "ripgrep": ToolCallType.GREP_SEARCH,
    "semantic_search": ToolCallType.GREP_SEARCH,
    "search": ToolCallType.GREP_SEARCH,
    "file_search": ToolCallType.GREP_SEARCH,
    # File writes
    "write_file": ToolCallType.FILE_WRITE,
    "create_file": ToolCallType.FILE_WRITE,
    "edit_file": ToolCallType.FILE_WRITE,
    "replace_string_in_file": ToolCallType.FILE_WRITE,
    "insert_text": ToolCallType.FILE_WRITE,
    # Command execution
    "run_command": ToolCallType.COMMAND_EXECUTION,
    "bash": ToolCallType.COMMAND_EXECUTION,
    "terminal": ToolCallType.COMMAND_EXECUTION,
    "run_in_terminal": ToolCallType.COMMAND_EXECUTION,
    "execute": ToolCallType.COMMAND_EXECUTION,
    # Test runs
    "run_tests": ToolCallType.TEST_RUN,
    "test": ToolCallType.TEST_RUN,
    "pytest": ToolCallType.TEST_RUN,
    "jest": ToolCallType.TEST_RUN,
    # Git
    "git_status": ToolCallType.GIT_OPERATION,
    "git_diff": ToolCallType.GIT_OPERATION,
    "git_log": ToolCallType.GIT_OPERATION,
    "git_commit": ToolCallType.GIT_OPERATION,
    # Linting (categorized as test for compression purposes)
    "lint": ToolCallType.TEST_RUN,
    "eslint": ToolCallType.TEST_RUN,
    "ruff": ToolCallType.TEST_RUN,
    "mypy": ToolCallType.TEST_RUN,
}


@dataclass(frozen=True)
class ClassifiedToolCall:
    """A tool call with its classification metadata."""

    name: str
    tool_type: ToolCallType
    compressibility: float
    value_score: float
    arguments: dict[str, Any]
    result_tokens: int = 0

    @property
    def is_highly_compressible(self) -> bool:
        """True if this tool call result can be aggressively compressed."""
        return self.compressibility >= 0.70

    @property
    def is_high_value(self) -> bool:
        """True if this tool call result should be preserved carefully."""
        return self.value_score >= 0.75

    @property
    def compression_priority(self) -> float:
        """Priority for compression (higher = compress first).

        Combines compressibility and inverse value: high compressibility
        + low value = compress first.
        """
        return self.compressibility * (1.0 - self.value_score)


class ToolCallClassifier:
    """Classifies tool calls by type and compressibility.

    Used by the compression scheduler to determine which tool call
    results should be compressed first and how aggressively.

    Example:
        >>> classifier = ToolCallClassifier()
        >>> classified = classifier.classify("list_dir", {"path": "/src"})
        >>> classified.tool_type
        ToolCallType.DIRECTORY_LISTING
        >>> classified.compressibility
        0.90
    """

    def __init__(self, custom_mappings: dict[str, ToolCallType] | None = None):
        """Initialize classifier with optional custom tool mappings.

        Args:
            custom_mappings: Additional tool name → type mappings.
        """
        self._type_map = dict(_TOOL_TYPE_MAP)
        if custom_mappings:
            self._type_map.update(custom_mappings)

    def classify(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        result_tokens: int = 0,
    ) -> ClassifiedToolCall:
        """Classify a tool call by name and arguments.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool call arguments (used for heuristic refinement).
            result_tokens: Number of tokens in the tool result.

        Returns:
            ClassifiedToolCall with type, compressibility, and value metadata.
        """
        arguments = arguments or {}
        tool_type = self._resolve_type(tool_name, arguments)
        compressibility = COMPRESSIBILITY[tool_type]
        value_score = VALUE_SCORES[tool_type]

        # Refine based on arguments
        tool_type, compressibility, value_score = self._refine_classification(
            tool_type, compressibility, value_score, tool_name, arguments
        )

        return ClassifiedToolCall(
            name=tool_name,
            tool_type=tool_type,
            compressibility=compressibility,
            value_score=value_score,
            arguments=arguments,
            result_tokens=result_tokens,
        )

    def classify_batch(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> list[ClassifiedToolCall]:
        """Classify multiple tool calls at once.

        Args:
            tool_calls: List of dicts with 'name', 'arguments', 'result_tokens'.

        Returns:
            List of ClassifiedToolCall instances.
        """
        return [
            self.classify(
                tc.get("name", "unknown"),
                tc.get("arguments", {}),
                tc.get("result_tokens", 0),
            )
            for tc in tool_calls
        ]

    def sort_by_compression_priority(
        self,
        classified: list[ClassifiedToolCall],
    ) -> list[ClassifiedToolCall]:
        """Sort tool calls by compression priority (highest first).

        Use this to determine which tool results to compress first
        when approaching Smart Zone limits.
        """
        return sorted(classified, key=lambda c: c.compression_priority, reverse=True)

    def _resolve_type(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallType:
        """Resolve tool type from name and arguments."""
        name_lower = tool_name.lower()

        # Direct lookup
        if name_lower in self._type_map:
            return self._type_map[name_lower]

        # Heuristic: check if command args hint at test/git/etc
        if "command" in arguments:
            cmd = str(arguments["command"]).lower()
            if any(t in cmd for t in ("pytest", "jest", "test", "cargo test")):
                return ToolCallType.TEST_RUN
            if cmd.startswith("git "):
                return ToolCallType.GIT_OPERATION
            if any(t in cmd for t in ("lint", "eslint", "ruff", "mypy")):
                return ToolCallType.TEST_RUN

        # Heuristic: path-based detection
        path = str(arguments.get("path", arguments.get("file", ""))).lower()
        if path:
            if any(path.endswith(ext) for ext in (".json", ".yaml", ".yml", ".toml")):
                return ToolCallType.CONFIG_READ
            if any(path.endswith(ext) for ext in (".md", ".rst", ".txt")):
                return ToolCallType.DOCUMENTATION

        return ToolCallType.UNKNOWN

    def _refine_classification(
        self,
        tool_type: ToolCallType,
        compressibility: float,
        value_score: float,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[ToolCallType, float, float]:
        """Refine classification based on contextual signals."""
        # Config files that are package manifests are higher value
        if tool_type == ToolCallType.CONFIG_READ:
            path = str(arguments.get("path", "")).lower()
            if any(
                name in path
                for name in ("package.json", "cargo.toml", "pyproject.toml")
            ):
                value_score = 0.85

        # Large file reads are more compressible (likely to have boilerplate)
        if tool_type == ToolCallType.FILE_READ:
            # If the file is very large, it has more compressible content
            lines = arguments.get("endLine", 0) - arguments.get("startLine", 0)
            if lines > 200:
                compressibility = 0.30

        return tool_type, compressibility, value_score
