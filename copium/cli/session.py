"""Session management CLI commands.

Provides compact/apply/expand/search commands for AI agent session archives.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from .main import main


@main.group()
def session():
    """Session archive management — compact, apply, expand, search."""
    pass


@session.command()
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output", "-o", type=click.Path(path_type=Path), default=None,
    help="Output path for compacted archive. Default: <input>_compacted.jsonl",
)
@click.option("--no-dedup", is_flag=True, help="Skip tool output deduplication.")
@click.option("--no-ansi", is_flag=True, help="Skip ANSI removal.")
@click.option("--no-preamble", is_flag=True, help="Skip assistant preamble collapse.")
@click.option("--threshold", type=float, default=0.85, help="Near-duplicate threshold (0-1).")
@click.option("--json-output", "as_json", is_flag=True, help="Output stats as JSON.")
def compact(
    input_path: Path,
    output: Path | None,
    no_dedup: bool,
    no_ansi: bool,
    no_preamble: bool,
    threshold: float,
    as_json: bool,
) -> None:
    """Compact a session archive by deduplicating and removing noise.

    Reads a JSONL session file (Claude Code, etc.), compresses it by
    deduplicating repeated tool outputs, removing assistant filler,
    and stripping ANSI noise.

    \b
    Examples:
        copium session compact ~/.claude/projects/.../session.jsonl
        copium session compact session.jsonl -o small.jsonl --threshold 0.9
    """
    from copium.session.archive import CompactConfig, SessionArchive
    from copium.session.compactor import SessionCompactor

    config = CompactConfig(
        deduplicate_tool_outputs=not no_dedup,
        collapse_assistant_preamble=not no_preamble,
        remove_ansi=not no_ansi,
        near_duplicate_threshold=threshold,
    )

    archive = SessionArchive(input_path)
    compactor = SessionCompactor(config)
    compacted, result = compactor.compact(archive)

    # Determine output path
    if output is None:
        output = input_path.with_stem(input_path.stem + "_compacted")

    compacted.to_jsonl(output)

    if as_json:
        click.echo(json.dumps({
            "input": str(input_path),
            "output": str(output),
            "original_messages": result.original_messages,
            "compacted_messages": result.compacted_messages,
            "original_tokens_est": result.original_tokens_est,
            "compacted_tokens_est": result.compacted_tokens_est,
            "savings_pct": round(result.savings_pct, 1),
            "dedup_hits": result.dedup_hits,
            "near_dedup_hits": result.near_dedup_hits,
            "preamble_collapsed": result.preamble_collapsed,
            "ansi_stripped": result.ansi_stripped,
        }, indent=2))
    else:
        click.echo(f"Compacted: {input_path.name}")
        click.echo(f"  Messages: {result.original_messages} → {result.compacted_messages}")
        click.echo(f"  Tokens (est): {result.original_tokens_est:,} → {result.compacted_tokens_est:,}")
        click.echo(f"  Savings: {result.savings_pct:.1f}%")
        click.echo(f"  Exact dedup hits: {result.dedup_hits}")
        click.echo(f"  Near-dedup hits: {result.near_dedup_hits}")
        click.echo(f"  Preamble collapsed: {result.preamble_collapsed}")
        click.echo(f"  ANSI stripped: {result.ansi_stripped}")
        click.echo(f"  Output: {output}")


@session.command("apply")
@click.argument("archive_path", type=click.Path(exists=True, path_type=Path))
@click.argument("query", required=False)
@click.option("--format", "fmt", type=click.Choice(["anthropic", "openai"]), default="anthropic")
@click.option("--max-messages", "-n", type=int, default=0, help="Max context messages (0=all).")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def apply_cmd(
    archive_path: Path,
    query: str | None,
    fmt: str,
    max_messages: int,
    output: Path | None,
) -> None:
    """Apply a compacted session as context for a new conversation.

    Converts the compacted archive into API-ready messages in the
    specified format (Anthropic or OpenAI).

    \b
    Examples:
        copium session apply compacted.jsonl "What was I working on?"
        copium session apply compacted.jsonl --format openai -o context.json
    """
    from copium.session.applicator import SessionApplicator
    from copium.session.archive import SessionArchive

    archive = SessionArchive(archive_path)
    applicator = SessionApplicator(
        max_context_messages=max_messages,
        format=fmt,
    )
    messages = applicator.apply(archive, new_query=query)

    output_json = json.dumps(messages, indent=2)
    if output:
        output.write_text(output_json, encoding="utf-8")
        click.echo(f"Applied {len(messages)} messages to {output}")
    else:
        click.echo(output_json)


@session.command()
@click.argument("archive_path", type=click.Path(exists=True, path_type=Path))
@click.option("--original", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to original archive for full reconstruction.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def expand(
    archive_path: Path,
    original: Path | None,
    output: Path | None,
) -> None:
    """Expand a compacted archive back to original form.

    If the original archive is provided, performs exact reconstruction.
    Otherwise, leaves reference markers in place (models understand them).

    \b
    Examples:
        copium session expand compacted.jsonl --original session.jsonl
        copium session expand compacted.jsonl -o restored.jsonl
    """
    from copium.session.archive import SessionArchive
    from copium.session.expander import SessionExpander

    archive = SessionArchive(archive_path)
    expander = SessionExpander(original_path=original)
    expanded = expander.expand(archive)

    if output is None:
        output = archive_path.with_stem(archive_path.stem + "_expanded")

    expanded.to_jsonl(output)
    click.echo(f"Expanded: {len(expanded)} messages → {output}")


@session.command("compact-all")
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--threshold", type=float, default=0.85)
@click.option("--recursive/--no-recursive", default=True)
def compact_all(
    directory: Path,
    output_dir: Path | None,
    threshold: float,
    recursive: bool,
) -> None:
    """Batch compact all session archives in a directory.

    \b
    Examples:
        copium session compact-all ~/.claude/ -o compacted/
        copium session compact-all ~/.claude/projects/ --threshold 0.9
    """
    from copium.session.archive import CompactConfig, SessionArchive
    from copium.session.compactor import SessionCompactor

    config = CompactConfig(near_duplicate_threshold=threshold)
    compactor = SessionCompactor(config)

    if output_dir is None:
        output_dir = directory / "compacted"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all JSONL files
    pattern = "**/*.jsonl" if recursive else "*.jsonl"
    jsonl_files = list(directory.glob(pattern))

    if not jsonl_files:
        click.echo(f"No .jsonl files found in {directory}")
        return

    total_savings = 0
    processed = 0

    for jsonl_path in jsonl_files:
        try:
            archive = SessionArchive(jsonl_path)
            if not archive.messages:
                continue

            compacted, result = compactor.compact(archive)
            out_path = output_dir / jsonl_path.name
            compacted.to_jsonl(out_path)
            total_savings += result.original_tokens_est - result.compacted_tokens_est
            processed += 1
            click.echo(f"  {jsonl_path.name}: {result.savings_pct:.0f}% savings")
        except Exception as e:
            click.echo(f"  {jsonl_path.name}: ERROR - {e}", err=True)

    click.echo(f"\nProcessed {processed}/{len(jsonl_files)} files")
    click.echo(f"Total token savings (est): {total_savings:,}")


@session.command()
@click.argument("archive_path", type=click.Path(exists=True, path_type=Path))
@click.option("--json-output", "as_json", is_flag=True, help="Output as JSON.")
def summary(archive_path: Path, as_json: bool) -> None:
    """Show summary of a session archive.

    \b
    Examples:
        copium session summary session.jsonl
    """
    from copium.session.archive import SessionArchive

    archive = SessionArchive(archive_path)

    # Count by type
    type_counts: dict[str, int] = {}
    for msg in archive.messages:
        type_counts[msg.type] = type_counts.get(msg.type, 0) + 1

    tokens_est = archive.token_estimate()
    total_chars = sum(len(m.content) for m in archive.messages)

    if as_json:
        click.echo(json.dumps({
            "path": str(archive_path),
            "messages": len(archive),
            "tokens_est": tokens_est,
            "chars": total_chars,
            "is_compacted": archive.is_compacted,
            "type_counts": type_counts,
        }, indent=2))
    else:
        click.echo(f"Session: {archive_path.name}")
        click.echo(f"  Messages: {len(archive)}")
        click.echo(f"  Tokens (est): {tokens_est:,}")
        click.echo(f"  Characters: {total_chars:,}")
        click.echo(f"  Compacted: {'Yes' if archive.is_compacted else 'No'}")
        click.echo(f"  Message types:")
        for mtype, count in sorted(type_counts.items()):
            click.echo(f"    {mtype}: {count}")
