"""Universal hook generator for any agent.

Generates shell hook scripts that can be used by any AI coding agent
to compress tool outputs before they enter the LLM context.

Plan §8.5: Universal Hook Pattern.

Usage:
    copium hook claude     # Generates Claude settings.json hooks
    copium hook codex      # Generates Codex AGENTS.md + config.toml
    copium hook cursor     # Generates .cursorrules + settings
    copium hook generic    # Generates generic shell hooks (works with any agent)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from .main import main


# Hook templates for different agents
_HOOK_TEMPLATES = {
    "claude": {
        "description": "Claude Code PreToolUse hooks for settings.json",
        "generator": "_generate_claude_hooks",
    },
    "codex": {
        "description": "Codex AGENTS.md instructions + config.toml",
        "generator": "_generate_codex_hooks",
    },
    "cursor": {
        "description": "Cursor .cursorrules + workspace settings",
        "generator": "_generate_cursor_hooks",
    },
    "generic": {
        "description": "Generic shell functions for any agent",
        "generator": "_generate_generic_hooks",
    },
}


@main.command("hook")
@click.argument(
    "agent",
    type=click.Choice(list(_HOOK_TEMPLATES.keys())),
)
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    help="Output file path (default: stdout)",
)
@click.option(
    "--max-lines",
    default=200,
    type=int,
    help="Max lines for compress-read (default: 200)",
)
@click.option(
    "--max-results",
    default=50,
    type=int,
    help="Max results for compress-search (default: 50)",
)
def hook_cmd(
    agent: str,
    output: Path | None,
    max_lines: int,
    max_results: int,
) -> None:
    """Generate hook configuration for the specified agent.

    \b
    Examples:
        copium hook claude                    # Print to stdout
        copium hook claude -o hooks.json      # Write to file
        copium hook generic > copium-hooks.sh # Shell script for any agent

    \b
    Generated hooks include:
    - compress-read: Compresses large file reads
    - compress-search: Compresses large search results
    """
    generator_name = _HOOK_TEMPLATES[agent]["generator"]
    generator = globals()[generator_name]

    content = generator(
        max_lines=max_lines,
        max_results=max_results,
    )

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
        click.echo(f"Hooks written to {output}")
    else:
        click.echo(content)


def _generate_claude_hooks(*, max_lines: int, max_results: int) -> str:
    """Generate Claude Code PreToolUse hooks for settings.json."""
    hooks = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [{
                        "type": "command",
                        "command": f"copium compress-read --max-lines {max_lines}",
                    }],
                },
                {
                    "matcher": "Grep",
                    "hooks": [{
                        "type": "command",
                        "command": f"copium compress-search --max-results {max_results}",
                    }],
                },
            ],
        },
    }

    return json.dumps(hooks, indent=2)


def _generate_codex_hooks(*, max_lines: int, max_results: int) -> str:
    """Generate Codex AGENTS.md instructions and config.toml."""
    agents_md = f"""<!-- copium:hooks -->
# Copium Hooks for Codex

When running shell commands, use copium compression to reduce context usage:

## File Reads
Large file reads are automatically compressed. For manual control:
```bash
copium compress-read --max-lines {max_lines} < file.txt
```

## Search Results
Large grep/ripgrep results are compressed. For manual control:
```bash
copium compress-search --max-results {max_results} < search_output.txt
```

## Configuration
Add to your Codex config.toml:
```toml
[model_providers.copium]
name = "OpenAI via Copium proxy"
base_url = "http://127.0.0.1:8787/v1"
supports_websockets = true
```

Then run: `copium wrap codex`
<!-- /copium:hooks -->
"""

    return agents_md


def _generate_cursor_hooks(*, max_lines: int, max_results: int) -> str:
    """Generate Cursor .cursorrules and workspace settings."""
    cursor_rules = f"""<!-- copium:hooks -->
# Copium Hooks for Cursor

## RTK Instructions
When running shell commands, always prefix with `rtk` for CLI stdout compression:
```bash
rtk git status
rtk grep pattern
rtk pytest tests/
```

## Copium Compression Hooks
For large file reads and search results, use copium compression:

### File Reads
```bash
copium compress-read --max-lines {max_lines} < large_file.py
```

### Search Results
```bash
copium compress-search --max-results {max_results} < grep_output.txt
```

## Proxy Configuration
Configure Cursor to use Copium proxy:
1. Open Cursor Settings
2. Set OpenAI API Base URL to: `http://127.0.0.1:8787/v1`
3. Or run: `copium wrap cursor` for setup instructions
<!-- /copium:hooks -->
"""

    # Also generate workspace settings
    workspace_settings = {
        "copium": {
            "proxyUrl": "http://127.0.0.1:8787",
            "compressRead": {"maxLines": max_lines},
            "compressSearch": {"maxResults": max_results},
        }
    }

    return f"""# .cursorrules
{cursor_rules}

# .cursor/settings.json (workspace settings)
{json.dumps(workspace_settings, indent=2)}
"""


def _generate_generic_hooks(*, max_lines: int, max_results: int) -> str:
    """Generate generic shell hooks for any agent."""
    return f"""#!/bin/bash
# copium-hooks.sh — Source this in your agent's environment
# Generated by: copium hook generic
#
# This script provides shell functions for compressing tool outputs
# using Copium's compression utilities.
#
# Usage:
#   source copium-hooks.sh
#   copium_compress_read < file.py
#   copium_compress_search < grep_output.txt
#

# Compress file reads - keeps first N lines + structure summary
copium_compress_read() {{
    local max_lines="${{1:-{max_lines}}}"
    copium compress-read --max-lines "$max_lines"
}}

# Compress search results - keeps top N matches
copium_compress_search() {{
    local max_results="${{1:-{max_results}}}"
    copium compress-search --max-results "$max_results"
}}

# Compress diff output
copium_compress_diff() {{
    copium compress-diff "$@"
}}

# Check if copium is available
if ! command -v copium &> /dev/null; then
    echo "Warning: copium not found in PATH. Hooks will not work." >&2
    # Provide no-op fallbacks
    copium_compress_read() {{ cat; }}
    copium_compress_search() {{ cat; }}
    copium_compress_diff() {{ cat; }}
fi

# Export functions for use in subshells
export -f copium_compress_read
export -f copium_compress_search
export -f copium_compress_diff

echo "Copium hooks loaded. Available functions:"
echo "  copium_compress_read [--max-lines N]"
echo "  copium_compress_search [--max-results N]"
echo "  copium_compress_diff"
"""


if __name__ == "__main__":
    hook_cmd()