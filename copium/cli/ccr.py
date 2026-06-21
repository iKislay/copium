"""CCR debugging CLI commands."""

import json

import click

from .main import main


@main.group()
def ccr():
    """CCR (Compress-Cache-Retrieve) debugging commands."""
    pass


@ccr.command()
@click.option("--limit", "-n", default=20, help="Maximum entries to show")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed info")
def list(limit: int, verbose: bool) -> None:
    """List CCR entries."""
    from copium.cache.compression_store import get_compression_store

    store = get_compression_store()
    entries = store._backend._entries  # Access internal entries

    click.echo(f"CCR Store: {len(entries)} entries")
    click.echo("-" * 60)

    count = 0
    for hash_key, entry in entries.items():
        if count >= limit:
            break

        if entry.is_expired():
            continue

        age_seconds = int(entry.created_at - __import__("time").time())
        status = "EXPIRED" if entry.is_expired() else "active"

        if verbose:
            click.echo(f"Hash: {hash_key}")
            click.echo(f"  Tool: {entry.tool_name or 'unknown'}")
            click.echo(f"  Items: {entry.original_item_count} -> {entry.compressed_item_count}")
            click.echo(f"  Tokens: {entry.original_tokens} -> {entry.compressed_tokens}")
            click.echo(f"  Age: {-age_seconds}s / TTL: {entry.ttl}s")
            click.echo(f"  Retrievals: {entry.retrieval_count}")
            click.echo(f"  Checksum: {entry.checksum or 'none'}")
            click.echo()
        else:
            click.echo(f"{hash_key[:12]}... | {entry.tool_name or 'unknown':20} | "
                      f"{entry.original_item_count:5} items | {-age_seconds:5}s")
        
        count += 1

    if len(entries) > limit:
        click.echo(f"\n... and {len(entries) - limit} more entries")


@ccr.command()
@click.argument("hash_key")
def inspect(hash_key: str) -> None:
    """Inspect a specific CCR entry."""
    from copium.cache.compression_store import get_compression_store

    store = get_compression_store()
    entry = store._backend.get(hash_key)

    if entry is None:
        click.echo(f"Entry not found: {hash_key}")
        return

    click.echo(f"Hash: {entry.hash}")
    click.echo(f"Tool: {entry.tool_name or 'unknown'}")
    click.echo(f"Tool Call ID: {entry.tool_call_id or 'none'}")
    click.echo(f"Query Context: {entry.query_context or 'none'}")
    click.echo(f"Original Items: {entry.original_item_count}")
    click.echo(f"Compressed Items: {entry.compressed_item_count}")
    click.echo(f"Original Tokens: {entry.original_tokens}")
    click.echo(f"Compressed Tokens: {entry.compressed_tokens}")
    click.echo(f"Compression Strategy: {entry.compression_strategy or 'unknown'}")
    click.echo(f"Tool Signature Hash: {entry.tool_signature_hash or 'none'}")
    click.echo(f"Created At: {entry.created_at}")
    click.echo(f"TTL: {entry.ttl}s")
    click.echo(f"Expired: {entry.is_expired()}")
    click.echo(f"Retrieval Count: {entry.retrieval_count}")
    click.echo(f"Last Accessed: {entry.last_accessed or 'never'}")
    click.echo(f"Checksum: {entry.checksum or 'none'}")
    click.echo(f"Search Queries: {entry.search_queries}")


@ccr.command()
@click.argument("hash_key")
def retrieve(hash_key: str) -> None:
    """Test retrieval of a CCR entry."""
    from copium.cache.compression_store import get_compression_store

    store = get_compression_store()
    entry = store.retrieve(hash_key)

    if entry is None:
        click.echo(f"Retrieval failed: Entry not found or expired")
        return

    click.echo(f"Retrieval successful!")
    click.echo(f"Hash: {entry.hash}")
    click.echo(f"Items: {entry.original_item_count}")
    click.echo(f"Checksum verified: {entry.checksum is not None}")

    # Show preview of content
    preview = entry.original_content[:500]
    if len(entry.original_content) > 500:
        preview += "..."
    click.echo(f"\nContent preview:\n{preview}")


@ccr.command()
def verify() -> None:
    """Verify integrity of all CCR entries."""
    from copium.cache.compression_store import get_compression_store

    store = get_compression_store()
    entries = store._backend._entries

    total = 0
    valid = 0
    invalid = 0
    expired = 0

    for hash_key, entry in entries.items():
        total += 1

        if entry.is_expired():
            expired += 1
            continue

        if entry.checksum is None:
            # No checksum to verify
            valid += 1
            continue

        import hashlib
        actual_checksum = hashlib.sha256(entry.original_content.encode()).hexdigest()[:16]
        if actual_checksum == entry.checksum:
            valid += 1
        else:
            invalid += 1
            click.echo(f"INTEGRITY FAILURE: {hash_key}")
            click.echo(f"  Expected: {entry.checksum}")
            click.echo(f"  Actual:   {actual_checksum}")

    click.echo(f"\nVerification complete:")
    click.echo(f"  Total entries: {total}")
    click.echo(f"  Valid: {valid}")
    click.echo(f"  Invalid: {invalid}")
    click.echo(f"  Expired: {expired}")


@ccr.command()
def stats() -> None:
    """Show CCR statistics."""
    from copium.cache.compression_store import get_compression_store

    store = get_compression_store()
    entries = store._backend._entries

    total = len(entries)
    active = sum(1 for e in entries.values() if not e.is_expired())
    expired = total - active

    total_original_tokens = sum(e.original_tokens for e in entries.values() if not e.is_expired())
    total_compressed_tokens = sum(e.compressed_tokens for e in entries.values() if not e.is_expired())
    total_retrievals = sum(e.retrieval_count for e in entries.values())

    # Group by tool name
    by_tool = {}
    for entry in entries.values():
        if entry.is_expired():
            continue
        tool = entry.tool_name or "unknown"
        if tool not in by_tool:
            by_tool[tool] = {"count": 0, "tokens": 0}
        by_tool[tool]["count"] += 1
        by_tool[tool]["tokens"] += entry.original_tokens

    click.echo("CCR Statistics")
    click.echo("=" * 40)
    click.echo(f"Total entries: {total}")
    click.echo(f"Active: {active}")
    click.echo(f"Expired: {expired}")
    click.echo(f"Total original tokens: {total_original_tokens:,}")
    click.echo(f"Total compressed tokens: {total_compressed_tokens:,}")
    click.echo(f"Total retrievals: {total_retrievals}")
    
    if by_tool:
        click.echo("\nBy tool:")
        for tool, stats in sorted(by_tool.items(), key=lambda x: -x[1]["count"]):
            click.echo(f"  {tool:20} | {stats['count']:5} entries | {stats['tokens']:10,} tokens")
