# Hermes Agent Integration

CCR retrieval plugin for [Hermes Agent](https://hermes-agent.nousresearch.com/) (Nous Research). Gives Hermes a native `copium_retrieve` tool so compression markers produced by the copium proxy are no longer a black box — the agent can fetch the original content back on demand instead of guessing or re-running commands.

## Why this is needed

When Hermes routes its LLM traffic through `copium proxy`, large tool outputs get compressed into markers like:

```
[1500 items compressed to 50. Retrieve more: hash=abc123]   # Kompress path
<<ccr:abc123>> / <<ccr:abc123,base64,4.5KB>>                # SmartCrusher opaque-blob path
```

Claude Code users get the `copium_retrieve` MCP tool injected automatically. Hermes registers its own tools, so without this plugin the markers are irreversible from the agent's point of view — in practice the model either re-runs the original command (wasting tokens/time) or, worse, treats `ccr:abc123` as a file path and tries to `cat` it.

This plugin closes the loop by calling the proxy's `POST /v1/retrieve` HTTP endpoint directly. It complements (does not overlap with) `copium wrap hermes` proxy-side support.

## Install

1. Copy the plugin into Hermes's user plugin directory:

   ```bash
   mkdir -p ~/.hermes/plugins
   cp -r copium_retrieve ~/.hermes/plugins/
   ```

2. Enable it in `~/.hermes/config.yaml`:

   ```yaml
   toolsets:
     - hermes-cli
     - web
     - copium        # add this

   plugins:
     enabled:
       - copium_retrieve
   ```

   > Note: once the `plugins.enabled` key exists it acts as an explicit allowlist — list any other user plugins you already rely on.

3. Restart the Hermes gateway / TUI (plugin discovery is cached per process).

## Recommended proxy configuration

Hermes tool names don't match copium's built-in `DEFAULT_EXCLUDE_TOOLS` (which protects Claude Code's `Read`/`Grep`/`Edit`/...), so two exclusions are strongly recommended on the proxy side:

```bash
COPIUM_EXCLUDE_TOOLS=read_file,copium_retrieve
```

- `read_file` — Hermes's file reads are reference data the agent needs verbatim, same rationale as Claude Code's `Read`.
- `copium_retrieve` — without this, retrieved originals get re-compressed on the next request, producing an endless marker→retrieve→marker loop.

## Behavior

- Accepts the bare hash or the whole marker — `<<ccr:abc123,base64,4.5KB>>`, `ccr:abc123`, and `hash=abc123` are all normalized to `abc123`.
- Optional `query` parameter filters very large results via the proxy's BM25 search.
- Clear, actionable errors: expired hash (TTL) and proxy-unreachable cases both tell the model to re-run the original command instead of retrying blindly.

## Requirements

- copium proxy running on `127.0.0.1:8787` (edit `_PROXY_URL` in `__init__.py` otherwise)
- `httpx` (already a Hermes dependency)

Tested against copium 0.22.4 and 0.23.0 with Hermes Agent on macOS and Linux.
