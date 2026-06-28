"""Session management CLI commands.

Provides compact/apply/expand/search/export/import commands for
AI agent session archives. Supports Claude Code, Cursor, Aider,
and OpenCode session formats with cross-agent context sharing.
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
@click.option("--agent", type=click.Choice(["auto", "claude_code", "cursor", "aider", "opencode"]),
              default="auto", help="Session format (auto-detect by default).")
@click.option("--json-output", "as_json", is_flag=True, help="Output stats as JSON.")
def compact(
    input_path: Path,
    output: Path | None,
    no_dedup: bool,
    no_ansi: bool,
    no_preamble: bool,
    threshold: float,
    agent: str,
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
    agent_format = archive.detect_format()

    if as_json:
        click.echo(json.dumps({
            "path": str(archive_path),
            "messages": len(archive),
            "tokens_est": tokens_est,
            "chars": total_chars,
            "is_compacted": archive.is_compacted,
            "format": agent_format,
            "type_counts": type_counts,
        }, indent=2))
    else:
        click.echo(f"Session: {archive_path.name}")
        click.echo(f"  Format: {agent_format}")
        click.echo(f"  Messages: {len(archive)}")
        click.echo(f"  Tokens (est): {tokens_est:,}")
        click.echo(f"  Characters: {total_chars:,}")
        click.echo(f"  Compacted: {'Yes' if archive.is_compacted else 'No'}")
        click.echo(f"  Message types:")
        for mtype, count in sorted(type_counts.items()):
            click.echo(f"    {mtype}: {count}")


@session.command()
@click.argument("query")
@click.option("--agent", type=str, default=None, help="Filter by agent (claude_code, cursor, aider, opencode).")
@click.option("--role", type=str, default=None, help="Filter by role (user, assistant, tool).")
@click.option("--file", "file_path", type=str, default=None, help="Search for sessions referencing this file.")
@click.option("--max-results", "-n", type=int, default=20)
@click.option("--json-output", "as_json", is_flag=True)
def search(
    query: str,
    agent: str | None,
    role: str | None,
    file_path: str | None,
    max_results: int,
    as_json: bool,
) -> None:
    """Search across all indexed session archives.

    Uses FTS5 full-text search with Porter stemming. Supports AND, OR, NOT.

    \b
    Examples:
        copium session search "authentication bug"
        copium session search "auth" --agent claude_code
        copium session search --file src/auth.ts "fix"
    """
    from copium.session.search import SearchConfig, SessionSearch

    config = SearchConfig(max_results=max_results)
    searcher = SessionSearch(config)

    if file_path:
        results = searcher.search_file(file_path, agent=agent)
    else:
        results = searcher.search(query, agent=agent, role=role, max_results=max_results)

    if as_json:
        click.echo(json.dumps([
            {
                "session_path": r.session_path,
                "turn_index": r.turn_index,
                "role": r.role,
                "snippet": r.content_snippet,
                "score": r.score,
                "agent": r.agent,
            }
            for r in results
        ], indent=2))
    else:
        if not results:
            click.echo("No results found.")
            return

        click.echo(f"Found {len(results)} results:\n")
        for i, r in enumerate(results, 1):
            agent_label = f" [{r.agent}]" if r.agent else ""
            click.echo(f"  {i}. {Path(r.session_path).name}{agent_label} (turn {r.turn_index}, {r.role})")
            click.echo(f"     {r.content_snippet[:150]}")
            click.echo()

    searcher.close()


@session.command("index")
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option("--agent", type=str, default="", help="Force agent type for all files.")
@click.option("--recursive/--no-recursive", default=True)
def index_cmd(directory: Path, agent: str, recursive: bool) -> None:
    """Index session archives for search.

    \b
    Examples:
        copium session index ~/.claude/
        copium session index ~/.cursor/conversations/ --agent cursor
    """
    from copium.session.search import SessionSearch

    searcher = SessionSearch()
    count = searcher.index_directory(directory, agent=agent, recursive=recursive)
    click.echo(f"Indexed {count} messages from {directory}")

    stats = searcher.stats()
    click.echo(f"Total index: {stats['sessions']} sessions, {stats['messages']} messages")
    searcher.close()


@session.command("adapters")
def list_adapters_cmd() -> None:
    """List all available session format adapters."""
    from copium.session.adapters import list_adapters

    adapters = list_adapters()
    click.echo("Available session adapters:")
    for name in sorted(adapters):
        click.echo(f"  - {name}")


@session.command("diff")
@click.argument("path_a", type=click.Path(exists=True, path_type=Path))
@click.argument("path_b", type=click.Path(exists=True, path_type=Path))
@click.option("--json-output", "as_json", is_flag=True)
def diff_cmd(path_a: Path, path_b: Path, as_json: bool) -> None:
    """Compare two session archives.

    Shows differences in message count, content, and compression stats.

    \b
    Examples:
        copium session diff original.jsonl compacted.jsonl
    """
    from copium.session.archive import SessionArchive

    archive_a = SessionArchive(path_a)
    archive_b = SessionArchive(path_b)

    tokens_a = archive_a.token_estimate()
    tokens_b = archive_b.token_estimate()
    delta_tokens = tokens_a - tokens_b
    delta_pct = (delta_tokens / tokens_a * 100) if tokens_a > 0 else 0

    if as_json:
        click.echo(json.dumps({
            "path_a": str(path_a),
            "path_b": str(path_b),
            "messages_a": len(archive_a),
            "messages_b": len(archive_b),
            "tokens_a": tokens_a,
            "tokens_b": tokens_b,
            "delta_tokens": delta_tokens,
            "delta_pct": round(delta_pct, 1),
            "a_compacted": archive_a.is_compacted,
            "b_compacted": archive_b.is_compacted,
        }, indent=2))
    else:
        click.echo(f"Session A: {path_a.name}")
        click.echo(f"  Messages: {len(archive_a)}, Tokens: {tokens_a:,}, Compacted: {archive_a.is_compacted}")
        click.echo(f"Session B: {path_b.name}")
        click.echo(f"  Messages: {len(archive_b)}, Tokens: {tokens_b:,}, Compacted: {archive_b.is_compacted}")
        click.echo(f"Delta: {delta_tokens:,} tokens ({delta_pct:.1f}%)")

        # Show message type differences
        types_a: dict[str, int] = {}
        types_b: dict[str, int] = {}
        for m in archive_a.messages:
            types_a[m.type] = types_a.get(m.type, 0) + 1
        for m in archive_b.messages:
            types_b[m.type] = types_b.get(m.type, 0) + 1

        all_types = sorted(set(list(types_a.keys()) + list(types_b.keys())))
        click.echo("Message types:")
        for t in all_types:
            a = types_a.get(t, 0)
            b = types_b.get(t, 0)
            diff = b - a
            sign = "+" if diff > 0 else ""
            click.echo(f"  {t}: {a} -> {b} ({sign}{diff})")


@session.command("stats")
def stats_cmd() -> None:
    """Show session index statistics."""
    from copium.session.search import SessionSearch

    searcher = SessionSearch()
    stats = searcher.stats()

    click.echo(f"Session Index: {stats['index_path']}")
    click.echo(f"  Sessions: {stats['sessions']}")
    click.echo(f"  Messages: {stats['messages']}")
    click.echo(f"  Total tokens (est): {stats['total_tokens_est']:,}")
    click.echo(f"  Agents:")
    for agent, count in sorted(stats.get("agents", {}).items()):
        click.echo(f"    {agent}: {count}")
    searcher.close()


@session.command("export")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["anthropic", "openai", "shared"]),
              default="shared", help="Output format.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--compact/--no-compact", default=True, help="Compact before export.")
def export_cmd(input_path: Path, fmt: str, output: Path | None, compact: bool) -> None:
    """Export a session to a cross-agent format.

    Converts any agent session to a portable format that can be imported
    into a different agent.

    \b
    Examples:
        copium session export claude-session.jsonl --format shared
        copium session export cursor-session.json --format openai -o context.json
    """
    from copium.session.archive import SessionArchive
    from copium.session.compactor import SessionCompactor
    from copium.session.applicator import SessionApplicator

    archive = SessionArchive(input_path)

    if compact:
        compactor = SessionCompactor()
        archive, result = compactor.compact(archive)
        click.echo(f"Compacted: {result.savings_pct:.1f}% savings")

    if fmt == "shared":
        # Export as portable JSONL (agent-agnostic)
        if output is None:
            output = input_path.with_stem(input_path.stem + "_shared")
            if output.suffix != ".jsonl":
                output = output.with_suffix(".jsonl")
        archive.to_jsonl(output)
        click.echo(f"Exported {len(archive)} messages to {output} (shared JSONL)")
    else:
        applicator = SessionApplicator(format=fmt)
        messages = applicator.apply(archive)
        output_json = json.dumps(messages, indent=2)
        if output is None:
            output = input_path.with_stem(input_path.stem + f"_{fmt}").with_suffix(".json")
        output.write_text(output_json, encoding="utf-8")
        click.echo(f"Exported {len(messages)} messages to {output} ({fmt} format)")


@session.command("import")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.option("--agent", type=click.Choice(["claude_code", "cursor", "aider", "opencode"]),
              required=True, help="Target agent format.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def import_cmd(input_path: Path, agent: str, output: Path | None) -> None:
    """Import a session from shared or another agent format.

    Converts a session archive to the target agent's native format.

    \b
    Examples:
        copium session import shared.jsonl --agent cursor -o cursor-session.json
    """
    from copium.session.archive import SessionArchive
    from copium.session.adapters import get_adapter

    archive = SessionArchive(input_path)
    adapter = get_adapter(agent)

    if adapter is None:
        click.echo(f"Unknown agent: {agent}", err=True)
        raise SystemExit(1)

    if output is None:
        suffix = ".jsonl" if agent in ("claude_code", "aider") else ".json"
        output = input_path.with_stem(input_path.stem + f"_{agent}").with_suffix(suffix)

    adapter.write(archive.messages, output)
    click.echo(f"Imported {len(archive)} messages to {output} ({agent} format)")


@session.command("replay")
@click.argument("archive_path", type=click.Path(exists=True, path_type=Path))
@click.option("--model", type=str, default=None, help="Model to replay with (e.g., gpt-4o, claude-haiku).")
@click.option("--compact/--no-compact", default=True, help="Compact before replay.")
@click.option("--dry-run", is_flag=True, help="Show what would be sent without calling the API.")
def replay_cmd(archive_path: Path, model: str | None, compact: bool, dry_run: bool) -> None:
    """Replay a session with a different model (experimental).

    Reads a session archive, optionally compacts it, and replays the
    user turns against a different model to see how it responds.

    \b
    Examples:
        copium session replay session.jsonl --model gpt-4o --dry-run
        copium session replay session.jsonl --model claude-haiku --compact
    """
    from copium.session.archive import SessionArchive
    from copium.session.compactor import SessionCompactor
    from copium.session.applicator import SessionApplicator

    archive = SessionArchive(archive_path)

    if compact:
        compactor = SessionCompactor()
        archive, result = compactor.compact(archive)
        click.echo(f"Compacted: {result.savings_pct:.1f}% savings ({result.original_tokens_est:,} → {result.compacted_tokens_est:,} tokens)")

    # Extract user turns only for replay
    user_turns = [m for m in archive.messages if m.role == "user"]

    if dry_run:
        click.echo(f"\n[Dry run] Would replay {len(user_turns)} user turns")
        if model:
            click.echo(f"  Model: {model}")
        click.echo(f"  Total messages: {len(archive)}")
        click.echo(f"  Estimated tokens: {archive.token_estimate():,}")
        click.echo("\nUser turns:")
        for i, turn in enumerate(user_turns[:5], 1):
            preview = turn.content[:100].replace("\n", " ")
            click.echo(f"  {i}. {preview}...")
        if len(user_turns) > 5:
            click.echo(f"  ... and {len(user_turns) - 5} more")
    else:
        click.echo("Session replay requires an API key configured.")
        click.echo("Use --dry-run to preview what would be sent.")
        click.echo(f"\nSession has {len(user_turns)} user turns, {archive.token_estimate():,} tokens")
