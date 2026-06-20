# @copium-ai/openclaw

Context compression plugin for [OpenClaw](https://github.com/openclaw/openclaw). Compresses tool outputs, code, logs, and structured data — 70-90% token savings with zero LLM calls.

## Install

Recommended one-command setup:

```bash
copium wrap openclaw
```

Manual install:

```bash
pip install "copium-ai[proxy]"
openclaw plugins install --dangerously-force-unsafe-install copium-ai/openclaw
```

This plugin can auto-start a local `copium proxy` when needed. OpenClaw treats process-launching plugins as unsafe by default, so `--dangerously-force-unsafe-install` is required even if you plan to use a remote proxy (the capability is declared at install time).

## Local Development Install (Detection-Friendly)

If you are testing from this repo, run npm install/build from the plugin directory so local launcher detection aligns with runtime paths. These linked installs are supported:

```bash
cd plugins/openclaw
npm install
npm run build
openclaw plugins install --dangerously-force-unsafe-install --link .
openclaw plugins install --dangerously-force-unsafe-install --link dist
```

From the repo root, install the plugin directory explicitly:

```bash
openclaw plugins install --dangerously-force-unsafe-install --link ./plugins/openclaw
```

Or, from inside `dist/`:

```bash
cd plugins/openclaw/dist
openclaw plugins install --dangerously-force-unsafe-install --link .
```

Why this matters:
- The plugin checks launchers in this order: PATH -> local npm bin -> global npm -> python.
- "local npm bin" means `plugins/openclaw/node_modules/.bin/copium` relative to the source checkout.
- Using `--link dist` (or `--link .` from `dist/`) still keeps runtime code adjacent to the checkout, and launcher detection falls back to PATH/global/python if a local npm bin is not present under the installed root.
- `plugins/openclaw` also carries a no-op hook shim so OpenClaw's hook-pack fallback treats the path as valid instead of emitting a misleading `package.json missing openclaw.hooks` warning.
- If you install from a `.tgz`, local npm bin may not exist in the installed extension and detection will fall back to PATH/global/python.

## Configure

Install automatically selects the `contextEngine` slot for `copium` on current OpenClaw releases. If you need to switch back manually, set `plugins.slots.contextEngine` to `"legacy"` or another engine id.

```json
{
  "plugins": {
    "entries": {
      "copium": {
        "enabled": true,
        "config": {
          "proxyUrl": "http://127.0.0.1:8787"
        }
      }
    },
    "slots": {
      "contextEngine": "copium"
    }
  }
}
```

`proxyUrl` is optional. If omitted, the plugin auto-detects on localhost:
- `http://127.0.0.1:<proxyPort>`
- `http://localhost:<proxyPort>`

Default `proxyPort` is `8787`.

### Upstream gateway routing

By default, the plugin also rewrites the built-in `openai-codex` provider base URL to the active Copium proxy at runtime. That means Codex provider traffic flows through Copium, so `/stats` can observe real upstream request and cache activity instead of only local context compression.

This does not replace Copium's existing Codex routing rules. The proxy already decides between `api.openai.com` and `chatgpt.com/backend-api/codex/responses` based on ChatGPT auth. The plugin change only points OpenClaw's provider config at the active proxy in memory and preserves the rest of the provider config.

You can also route additional provider ids such as `anthropic`, `github-copilot`, `google`, or `openrouter` through the same proxy:

```json
{
  "plugins": {
    "entries": {
      "copium": {
        "enabled": true,
        "config": {
          "gatewayProviderIds": ["openai-codex", "anthropic", "github-copilot", "google", "openrouter"]
        }
      }
    }
  }
}
```

When `gatewayProviderIds` is set, it becomes the exact list the plugin rewrites in memory for the current gateway process.

For convenience, the plugin also accepts family aliases:
- `codex` -> `openai-codex`
- `claude` -> `anthropic`
- `copilot` -> `github-copilot`
- `gemini` -> `google`

When OpenClaw has already resolved a provider's upstream `baseUrl`, the plugin preserves protocol-specific path segments while swapping only the origin. That keeps provider families on the right proxy route:
- Codex / ChatGPT backend: `/backend-api`
- OpenAI-compatible providers: `/v1` or `/api/v1`
- GitHub Copilot Claude-family models: `/anthropic`
- Gemini: `/v1beta`

GitHub Copilot is a special case because OpenClaw can route it through either OpenAI Responses or Anthropic Messages depending on the selected model. The plugin only rewrites Copilot when OpenClaw has already resolved the upstream `baseUrl`, so it can preserve the correct `/v1` or `/anthropic` path instead of guessing.

The routing is intentionally lightweight and reversible:
- the plugin does not persist provider `baseUrl` changes back to `openclaw.json`
- disabling the plugin, clearing `gatewayProviderIds`, or restarting without Copium restores OpenClaw's normal provider resolution
- if you want durable provider rewrites, use `copium wrap openclaw` instead of relying on plugin install side effects

If you need to disable that behavior:

```json
{
  "plugins": {
    "entries": {
      "copium": {
        "enabled": true,
        "config": {
          "routeCodexViaProxy": false
        }
      }
    }
  }
}
```

### Local proxy (auto-start)

When `proxyUrl` points to localhost (or is omitted), the plugin will auto-start `copium proxy` if no running proxy is detected. Launch order:
1. `copium` from `PATH`
2. local npm bin (`node_modules/.bin/copium`)
3. global npm bin
4. Python module (`python -m copium.cli proxy ...`)

If `pythonPath` is set, it is tried first in the Python fallback step.

Docker-native Copium installs intentionally leave `pythonPath` unset so this launcher order prefers the installed host `copium` wrapper on `PATH`, which then runs Copium in Docker.

### Remote proxy (connect-only)

Point `proxyUrl` to any reachable Copium instance:

```json
{
  "config": {
    "proxyUrl": "https://copium.example.com:8787"
  }
}
```

Remote URLs are **connect-only** — the plugin probes the URL at startup and fails fast if the proxy is not reachable. No subprocess is spawned for remote addresses.

## Manual Proxy Setup

If you prefer to manage the proxy yourself (or are running a remote instance), start it before launching OpenClaw:

Python install:

```bash
pip install "copium-ai[proxy]"
copium proxy --host 127.0.0.1 --port 8787
```

NPM install:

```bash
npm install -g copium-ai
copium proxy --host 127.0.0.1 --port 8787
```

## How It Works

Every time OpenClaw assembles context for the model, the plugin compresses tool outputs and large messages:

- **JSON arrays** (tool outputs, search results) — statistical selection keeps anomalies, errors, boundaries
- **Code** — AST-aware compression via tree-sitter
- **Logs** — pattern deduplication, keeps errors and boundaries
- **Text** — ML-based token compression

Compression is lossless via CCR (Compress-Cache-Retrieve): originals are stored and the agent gets a `copium_retrieve` tool to access full details when needed.

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `proxyUrl` | auto-detected | Optional URL of a Copium proxy. Local addresses (`http://127.0.0.1:<port>`, `http://localhost:<port>`) enable auto-start; remote URLs (`https://copium.example.com`) are connect-only. |
| `proxyPort` | `8787` | Port used for default auto-detect/auto-start when `proxyUrl` is not set. |
| `pythonPath` | auto-detected | Optional Python executable override for Python fallback launcher. |
| `autoStart` | `true` | Auto-start a local `copium proxy` if not already running (local URLs only; ignored for remote proxies) |
| `startupTimeoutMs` | `20000` | Time to wait for auto-started proxy to become healthy |
| `routeCodexViaProxy` | `true` | Rewrite OpenClaw's built-in `openai-codex` provider to use the active Copium proxy in memory so upstream Codex requests pass through Copium. |
| `gatewayProviderIds` | `[]` | Optional explicit list of OpenClaw provider ids to route through the active Copium proxy in memory. Friendly aliases `codex`, `claude`, `copilot`, and `gemini` are also accepted. When set, this overrides the default `openai-codex` routing list. |

## Comparison with lossless-claw

| | lossless-claw | copium |
|---|---|---|
| Compaction method | LLM summarization (DAG) | Content-aware compression (zero LLM) |
| Cost of compaction | Tokens (LLM calls) | Zero |
| Best for | Long conversations | Tool-heavy agents with large outputs |
| Retrieval | `lcm_grep`, `lcm_expand` | `copium_retrieve` (instant) |

## License

Apache-2.0
