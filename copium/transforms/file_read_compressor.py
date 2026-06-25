"""AST-aware file read compressor for large file reads.

Plan 5.2.1: File Read Compressor. When an agent reads a large file but only
needs a few functions, this compressor extracts the relevant AST nodes and
returns a compact excerpt plus a file structure summary, dramatically reducing
tokens compared to sending the entire file.

Compression strategy:
1. Parse the file into an AST using tree-sitter (when available).
2. Extract the file structure (imports, classes, functions, etc.).
3. If the read has an offset/limit hint, extract only the relevant region.
4. Otherwise, return headers + structure summary.
5. For non-parseable files, fall back to line-count truncation.

The compressor is designed to be used both by the proxy pipeline (on
tool_result blocks for Read tools) and by the Claude Code hook
(``copium compress-read``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..config import TransformResult
from ..tokenizer import Tokenizer
from .base import Transform

logger = logging.getLogger(__name__)

# Lazy tree-sitter imports
_tree_sitter_available: bool | None = None


def _check_tree_sitter() -> bool:
    global _tree_sitter_available
    if _tree_sitter_available is None:
        try:
            import tree_sitter_language_pack  # noqa: F401
            _tree_sitter_available = True
        except ImportError:
            _tree_sitter_available = False
    return _tree_sitter_available


# Language detection from file extension
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".sql": "sql",
    ".md": "markdown",
    ".rst": "markdown",
}

# Node types that are "interesting" for structure extraction
_TOP_LEVEL_NODE_TYPES: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition", "decorated_definition"},
    "javascript": {
        "function_declaration", "class_declaration",
        "export_statement", "arrow_function",
    },
    "typescript": {
        "function_declaration", "class_declaration",
        "interface_declaration", "type_alias_declaration",
        "export_statement", "arrow_function",
    },
    "rust": {
        "function_item", "struct_item", "enum_item", "impl_item",
        "trait_item", "mod_item",
    },
    "go": {
        "function_declaration", "type_declaration",
        "method_declaration",
    },
    "java": {
        "class_declaration", "interface_declaration",
        "method_declaration", "enum_declaration",
    },
}


class FileReadCompressorMode(Enum):
    """Compression mode for file reads."""

    STRUCTURE = "structure"
    REGION = "region"
    TRUNCATE = "truncate"


@dataclass
class FileReadCompressorConfig:
    """Configuration for file read compression."""

    max_lines: int = 200
    max_tokens_estimate: int = 4000
    structure_summary_max_items: int = 30
    context_lines_around_region: int = 5
    mode: FileReadCompressorMode = FileReadCompressorMode.STRUCTURE


@dataclass
class FileReadCompressionResult:
    """Result of file read compression."""

    compressed: str
    original_line_count: int
    compressed_line_count: int
    mode_used: FileReadCompressorMode
    language: str | None = None
    items_extracted: int = 0
    total_items: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.original_line_count == 0:
            return 1.0
        return self.compressed_line_count / self.original_line_count


@dataclass
class _ASTItem:
    """A single AST item (function, class, etc.) for structure extraction."""

    name: str
    node_type: str
    start_line: int
    end_line: int
    signature: str
    children: list[str] = field(default_factory=list)


def _detect_language(file_path: str | None) -> str | None:
    """Detect programming language from file extension."""
    if not file_path:
        return None
    for ext, lang in _EXT_TO_LANG.items():
        if file_path.endswith(ext):
            return lang
    return None


def _extract_structure_python(content: str) -> list[_ASTItem]:
    """Extract structure from Python code using regex (fallback for no tree-sitter)."""
    items: list[_ASTItem] = []
    lines = content.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        # Class definition
        m = re.match(r"^(\s*)class\s+(\w+)(?:\(.*?\))?:", line)
        if m:
            indent = len(m.group(1))
            name = m.group(2)
            start = i
            # Find end of class (next line at same or lower indent, or EOF)
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() and not next_line.strip().startswith("#"):
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent <= indent and next_line.strip():
                        break
                i += 1
            sig_line = lines[start].rstrip()
            items.append(_ASTItem(
                name=name, node_type="class",
                start_line=start + 1, end_line=i,
                signature=sig_line,
            ))
            continue

        # Function definition
        m = re.match(r"^(\s*)def\s+(\w+)\s*\(", line)
        if m:
            indent = len(m.group(1))
            name = m.group(2)
            start = i
            # Collect signature (may span multiple lines)
            sig = line.rstrip()
            i += 1
            paren_depth = sig.count("(") - sig.count(")")
            while i < len(lines) and paren_depth > 0:
                sig += " " + lines[i].strip()
                paren_depth += lines[i].count("(") - lines[i].count(")")
                i += 1
            # Find end of function body
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() and not next_line.strip().startswith("#"):
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent <= indent and next_line.strip():
                        break
                i += 1
            items.append(_ASTItem(
                name=name, node_type="function",
                start_line=start + 1, end_line=i,
                signature=sig[:200],
            ))
            continue

        i += 1

    return items


def _extract_structure_generic(content: str, lang: str) -> list[_ASTItem]:
    """Extract structure using regex patterns for various languages."""
    items: list[_ASTItem] = []
    lines = content.splitlines()

    patterns = {
        "rust": [
            (r"^\s*(?:pub\s+)?(?:fn|struct|enum|impl|trait|mod)\s+(\w+)", "definition"),
            (r"^\s*(?:pub\s+)?fn\s+(\w+)", "function"),
            (r"^\s*(?:pub\s+)?struct\s+(\w+)", "struct"),
            (r"^\s*(?:pub\s+)?enum\s+(\w+)", "enum"),
        ],
        "go": [
            (r"^\s*(?:func|type|var|const)\s+(\w+)", "definition"),
            (r"^\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)", "function"),
        ],
        "javascript": [
            (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"^\s*(?:export\s+)?class\s+(\w+)", "class"),
            (r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\(|function)", "function"),
        ],
        "typescript": [
            (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"^\s*(?:export\s+)?class\s+(\w+)", "class"),
            (r"^\s*(?:export\s+)?interface\s+(\w+)", "interface"),
            (r"^\s*(?:export\s+)?type\s+(\w+)", "type"),
        ],
        "java": [
            (r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|enum)\s+(\w+)", "definition"),
            (r"^\s*(?:public|private|protected)\s+[\w<>\[\]]+\s+(\w+)\s*\(", "function"),
        ],
    }

    lang_patterns = patterns.get(lang, [])
    seen_names: set[str] = set()

    for i, line in enumerate(lines):
        for pattern, node_type in lang_patterns:
            m = re.match(pattern, line)
            if m:
                name = m.group(1)
                if name not in seen_names:
                    seen_names.add(name)
                    items.append(_ASTItem(
                        name=name, node_type=node_type,
                        start_line=i + 1, end_line=i + 1,
                        signature=line.strip()[:200],
                    ))
                break

    return items


def _extract_structure_with_tree_sitter(content: str, lang: str) -> list[_ASTItem]:
    """Extract structure using tree-sitter (preferred when available)."""
    if not _check_tree_sitter():
        if lang == "python":
            return _extract_structure_python(content)
        return _extract_structure_generic(content, lang)

    try:
        from tree_sitter import Parser
        from tree_sitter_language_pack import get_language

        parser = Parser()
        parser.language = get_language(lang)  # type: ignore[arg-type]
        tree = parser.parse(content.encode("utf-8"))

        items: list[_ASTItem] = []
        _walk_tree(tree.root_node, items, depth=0)
        return items
    except Exception as e:
        logger.debug("tree-sitter extraction failed for %s: %s", lang, e)
        if lang == "python":
            return _extract_structure_python(content)
        return _extract_structure_generic(content, lang)


def _walk_tree(node: Any, items: list[_ASTItem], depth: int, max_depth: int = 3) -> None:
    """Walk AST tree and extract top-level items."""
    if depth > max_depth:
        return

    for child in node.children:
        node_type = child.type
        # Capture named top-level definitions
        if node_type in (
            "function_definition", "class_definition",
            "function_declaration", "class_declaration",
            "function_item", "struct_item", "enum_item",
            "impl_item", "trait_item", "mod_item",
            "method_definition", "method_declaration",
            "interface_declaration", "type_alias_declaration",
            "decorated_definition",
        ):
            name = _get_node_name(child)
            if name:
                sig = _get_signature_text(child)
                items.append(_ASTItem(
                    name=name,
                    node_type=node_type.replace("_definition", "").replace("_declaration", "").replace("_item", ""),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    signature=sig[:200],
                ))
        # Recurse into children for decorated definitions
        if node_type == "decorated_definition":
            _walk_tree(child, items, depth + 1, max_depth)


def _get_node_name(node: Any) -> str | None:
    """Extract the name from an AST node."""
    # Check for 'name' child
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8", errors="replace")
    # Check for 'name' field
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode("utf-8", errors="replace")
    return None


def _get_signature_text(node: Any, max_chars: int = 200) -> str:
    """Get the first line(s) of a node as a signature."""
    text = node.text.decode("utf-8", errors="replace")
    # Take first line or up to max_chars
    first_line = text.split("\n", 1)[0]
    return first_line[:max_chars]


def _format_structure_summary(
    items: list[_ASTItem],
    max_items: int = 30,
    language: str | None = None,
) -> str:
    """Format AST items into a compact structure summary."""
    if not items:
        return ""

    lines = [f"# File structure ({len(items)} items)"]
    if language:
        lines[0] += f" [{language}]"

    shown = items[:max_items]
    for item in shown:
        prefix = "class" if item.node_type == "class" else "fn"
        lines.append(f"  {prefix} {item.name} (L{item.start_line}-{item.end_line})")

    if len(items) > max_items:
        lines.append(f"  ... and {len(items) - max_items} more items")

    return "\n".join(lines)


def _extract_region(
    lines: list[str],
    start_line: int,
    end_line: int,
    context_lines: int = 5,
) -> str:
    """Extract a region of lines with context padding."""
    start_idx = max(0, start_line - 1 - context_lines)
    end_idx = min(len(lines), end_line + context_lines)

    result_lines: list[str] = []
    if start_idx > 0:
        result_lines.append(f"... {start_idx} lines before ...")

    result_lines.extend(lines[start_idx:end_idx])

    if end_idx < len(lines):
        result_lines.append(f"... {len(lines) - end_idx} lines after ...")

    return "\n".join(result_lines)


class FileReadCompressor(Transform):
    """AST-aware file read compressor.

    Compresses large file reads by extracting AST structure or relevant
    regions instead of returning the entire file content.

    When tree-sitter is available, uses AST parsing for precise structure
    extraction. Falls back to regex-based extraction for unsupported
    languages, and to line-count truncation for non-code files.
    """

    name = "file_read_compressor"

    def __init__(self, config: FileReadCompressorConfig | None = None):
        self.config = config or FileReadCompressorConfig()

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Apply file read compression to tool_result messages."""
        from ..config import TransformResult

        tokens_before = tokenizer.count_messages(messages)
        modified = False

        for msg in messages:
            if msg.get("role") != "tool":
                continue

            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            # Check if this looks like a file read result
            file_path = kwargs.get("file_path") or msg.get("file_path")
            if file_path is None:
                # Try to detect from content
                if len(content.splitlines()) <= self.config.max_lines:
                    continue  # Short enough, skip

            result = self.compress_file_content(
                content,
                file_path=str(file_path) if file_path else None,
            )

            if result.compressed_line_count < result.original_line_count:
                msg["content"] = result.compressed
                modified = True

        tokens_after = tokenizer.count_messages(messages)
        return TransformResult(
            messages=messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            transforms_applied=["file_read_compressor"] if modified else [],
        )

    def compress_file_content(
        self,
        content: str,
        file_path: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> FileReadCompressionResult:
        """Compress file content using AST-aware extraction.

        Args:
            content: Full file content to compress.
            file_path: Optional file path for language detection.
            start_line: Optional start line hint (1-indexed).
            end_line: Optional end line hint (1-indexed).

        Returns:
            FileReadCompressionResult with compressed content.
        """
        lines = content.splitlines()
        original_count = len(lines)

        if original_count < self.config.max_lines:
            return FileReadCompressionResult(
                compressed=content,
                original_line_count=original_count,
                compressed_line_count=original_count,
                mode_used=FileReadCompressorMode.STRUCTURE,
            )

        lang = _detect_language(file_path)

        # If explicit region requested, extract that
        if start_line is not None and end_line is not None:
            region = _extract_region(
                lines, start_line, end_line,
                context_lines=self.config.context_lines_around_region,
            )
            return FileReadCompressionResult(
                compressed=region,
                original_line_count=original_count,
                compressed_line_count=len(region.splitlines()),
                mode_used=FileReadCompressorMode.REGION,
                language=lang,
            )

        # Try AST extraction
        if lang:
            items = _extract_structure_with_tree_sitter(content, lang)
            if items:
                summary = _format_structure_summary(
                    items,
                    max_items=self.config.structure_summary_max_items,
                    language=lang,
                )
                # Also include first N lines as context header
                header = "\n".join(lines[:min(20, original_count)])
                compressed = f"{header}\n\n{summary}"

                return FileReadCompressionResult(
                    compressed=compressed,
                    original_line_count=original_count,
                    compressed_line_count=len(compressed.splitlines()),
                    mode_used=FileReadCompressorMode.STRUCTURE,
                    language=lang,
                    items_extracted=len(items),
                    total_items=len(items),
                )

        # Fallback: truncation
        truncated = lines[:self.config.max_lines]
        truncated.append(
            f"\n[... {original_count - self.config.max_lines} lines truncated "
            f"by copium compress-read (--max-lines {self.config.max_lines}). "
            f"Use offset/limit to read specific sections. ...]"
        )

        return FileReadCompressionResult(
            compressed="\n".join(truncated),
            original_line_count=original_count,
            compressed_line_count=len(truncated),
            mode_used=FileReadCompressorMode.TRUNCATE,
            language=lang,
        )
