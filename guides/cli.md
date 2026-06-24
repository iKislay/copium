# CLI Reference

This page is the authoritative reference for the **Python Copium CLI** exposed by the `copium` console script.

## Global behavior

### Entry points

- Console script: `copium`
- Python module entrypoint: `python -m copium.cli`

### Global options

| Option | Scope | Meaning |
|---|---|---|
| `--help`, `-?` | root, groups, commands | Show help and exit |
| `--version`, `-v` | root only | Show the Copium version and exit |

> `-v` is a **root-level version alias**. Inside subcommands such as `copium wrap claude -v`, `-v` keeps its subcommand meaning (`--verbose`), not version.

## Command index

| Command | Purpose | Docker-native parity |
|---|---|---|
| `copium install ...` | Install and manage persistent deployments | **python-native; Docker-native wrapper supports `persistent-docker` lifecycle subset** |
| `copium proxy` | Run the Copium proxy server | **native in container** |
| `copium learn` | Learn from past tool-call failures | **native in container** |
| `copium perf` | Summarize recent proxy performance | **native in container** |
| `copium evals ...` | Run memory evaluation workflows | **native in container** |
| `copium memory ...` | Inspect and manage stored memories | **native in container** |
| `copium mcp ...` | Install, inspect, remove, or serve MCP integration | **native in container** |
| `copium agents` | List detected AI agents and wrap status | **native in container** |
| `copium logs` | Tail proxy logs | **native in container** |
| `copium completions` | Generate shell completion scripts | **native in container** |
| `copium version` | Show version, platform, and install info | **native in container** |
| `copium doctor` | Diagnose installation and configuration | **native in container** |
| `copium wrap claude` | Start proxy and launch Claude Code | **host-bridged** |
| `copium wrap copilot` | Start proxy and launch GitHub Copilot CLI | **python-native only** |
| `copium wrap codex` | Start proxy and launch Codex CLI | **host-bridged** |
| `copium wrap aider` | Start proxy and launch Aider | **host-bridged** |
| `copium wrap cursor` | Start proxy and print Cursor config guidance | **host-bridged** |
| `copium wrap openclaw` | Install and configure the OpenClaw plugin | **host-bridged** |
| `copium unwrap openclaw` | Disable the Copium OpenClaw plugin | **host-bridged** |

## Captured `--help` output

The sections below capture the current top-level help output from the live CLI.

### `copium --help`

```text
Usage: copium [OPTIONS] COMMAND [ARGS]...

  Copium - The Context Optimization Layer for LLM Applications.

  Manage memories, run the optimization proxy, and analyze metrics.

  Examples:
      copium proxy              Start the optimization proxy
      copium memory list        List stored memories
      copium memory stats       Show memory statistics

Options:
  -v, --version  Show the version and exit.
  -?, --help     Show this message and exit.

Commands:
  evals   Memory evaluation commands.
  install Install and manage persistent Copium deployments.
  learn   Learn from past tool call failures to prevent future ones.
  mcp     MCP server for Claude Code integration.
  memory  Manage memories stored in Copium.
  perf    Analyze proxy performance from logs.
  proxy   Start the optimization proxy server.
  unwrap  Undo durable Copium wrapping for supported tools.
  wrap    Wrap CLI tools to run through Copium.
```

### Top-level command help snapshots

<details>
<summary><code>copium proxy --help</code></summary>

```text
Usage: copium proxy [OPTIONS]

  Start the optimization proxy server.

  Examples:
      copium proxy                    Start proxy on port 8787
      copium proxy --port 8080        Start proxy on port 8080
      copium proxy --no-optimize      Passthrough mode (no optimization)

  Usage with Claude Code:
      ANTHROPIC_BASE_URL=http://localhost:8787 claude

  Usage with OpenAI-compatible clients:
      OPENAI_BASE_URL=http://localhost:8787/v1 your-app
```

</details>

<details>
<summary><code>copium agents --help</code></summary>

```text
Usage: copium agents [OPTIONS]

  List all detected AI agents and their wrap status.

  Shows which agents are installed on your system and whether they are
  configured to route through the Copium proxy.

  Examples:
      copium agents              Show all known agents
      copium agents --installed  Show only installed agents
      copium agents --json       Machine-readable output

Options:
  --json       Output as JSON.
  --installed  Show only installed agents.
  -?, --help   Show this message and exit.
```

</details>

<details>
<summary><code>copium logs --help</code></summary>

```text
Usage: copium logs [OPTIONS]

  Tail Copium proxy logs.

  Shows recent log entries from the Copium proxy. Use --follow to watch
  logs in real time (Ctrl+C to stop).

  Examples:
      copium logs              Show last 100 lines
      copium logs -n 50        Show last 50 lines
      copium logs -f           Follow logs in real time
      copium logs --level ERROR  Show only errors

Options:
  -n, --tail INTEGER    Number of lines to show from the end.  [default: 100]
  -f, --follow          Follow log output (like tail -f).
  --level [DEBUG|INFO|WARNING|ERROR]
                        Filter by log level.
  --json                Output as JSON.
  -?, --help            Show this message and exit.
```

</details>

<details>
<summary><code>copium completions --help</code></summary>

```text
Usage: copium completions [OPTIONS] SHELL

  Generate shell completion scripts.

  Outputs a completion script to stdout. Redirect to the appropriate
  file to install.

  Examples:
      copium completions bash >> ~/.bash_completion
      copium completions zsh >> ~/.zshrc
      copium completions fish > ~/.config/fish/completions/copium.fish
      copium completions powershell | Out-String | Invoke-Expression

  After installing, reload your shell or run:
      source ~/.bash_completion   # bash
      source ~/.zshrc             # zsh
      exec fish                   # fish

Options:
  -?, --help  Show this message and exit.

Arguments:
  SHELL  Required. One of: bash, zsh, fish, powershell
```

</details>

<details>
<summary><code>copium version --help</code></summary>

```text
Usage: copium version [OPTIONS]

  Show Copium version, platform, and install info.

  Examples:
      copium version            Show version info
      copium version --json     Machine-readable output

Options:
  --json     Output as JSON.
  -?, --help  Show this message and exit.
```

</details>

<details>
<summary><code>copium learn --help</code></summary>

```text
Usage: copium learn [OPTIONS]

  Learn from past tool call failures to prevent future ones.
```

</details>

<details>
<summary><code>copium perf --help</code></summary>

```text
Usage: copium perf [OPTIONS]

  Analyze proxy performance from logs.
```

</details>

<details>
<summary><code>copium evals --help</code></summary>

```text
Usage: copium evals [OPTIONS] COMMAND [ARGS]...

  Memory evaluation commands.

Commands:
  memory     Run LoCoMo memory evaluation benchmark.
  memory-v2  Run LoCoMo V2 evaluation with LLM-controlled memory tools.
```

</details>

<details>
<summary><code>copium memory --help</code></summary>

```text
Usage: copium memory [OPTIONS] COMMAND [ARGS]...

  Manage memories stored in Copium.

Commands:
  delete  Delete one or more memories by ID.
  edit    Edit a memory's content or importance.
  export  Export all memories to JSON.
  import  Import memories from a JSON file.
  list    List stored memories with optional filters.
  prune   Prune memories matching specified criteria.
  purge   Delete ALL memories from the database.
  show    Show full details of a single memory.
  stats   Show memory store statistics.
```

</details>

<details>
<summary><code>copium mcp --help</code></summary>

```text
Usage: copium mcp [OPTIONS] COMMAND [ARGS]...

  MCP server for Claude Code integration.

Commands:
  install    Install Copium MCP server into Claude Code config.
  serve      Start the MCP server (called by Claude Code).
  status     Check Copium MCP configuration status.
  uninstall  Remove Copium MCP server from Claude Code config.
```

</details>

<details>
<summary><code>copium install --help</code></summary>

```text
Usage: copium install [OPTIONS] COMMAND [ARGS]...

  Install and manage persistent Copium deployments.

Options:
  -?, --help  Show this message and exit.

Commands:
  apply    Install a persistent Copium deployment.
  remove   Remove a persistent deployment and undo managed config.
  restart  Restart a persistent deployment.
  start    Start a persistent deployment.
  status   Show persistent deployment status.
  stop     Stop a persistent deployment.
```

</details>

<details>
<summary><code>copium wrap --help</code></summary>

```text
Usage: copium wrap [OPTIONS] COMMAND [ARGS]...

  Wrap CLI tools to run through Copium.

Commands:
  aider     Launch aider through Copium proxy.
  claude    Launch Claude Code through Copium proxy.
  copilot   Launch GitHub Copilot CLI through Copium proxy.
  codex     Launch OpenAI Codex CLI through Copium proxy.
  cursor    Start Copium proxy for use with Cursor.
  openclaw  Install and configure Copium OpenClaw plugin in one command.
```

</details>

<details>
<summary><code>copium unwrap --help</code></summary>

```text
Usage: copium unwrap [OPTIONS] COMMAND [ARGS]...

  Undo durable Copium wrapping for supported tools.

Commands:
  openclaw  Disable the Copium OpenClaw plugin and restore the legacy engine slot.
```

</details>

## `copium proxy`

Start the optimization proxy server.

```bash
copium proxy
copium proxy --port 8787
copium proxy --mode cache
```

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Host interface to bind |
| `--port`, `-p` | `8787` | Port to bind |
| `--mode` | runtime default | Optimization mode: `token`, `cache`, `token_mode`, `cache_mode`, `token_savings`, `cost_savings`, `token_copium` |
| `--no-optimize` | off | Disable optimization and operate in passthrough mode |
| `--no-cache` | off | Disable semantic caching |
| `--no-rate-limit` | off | Disable rate limiting |
| `--retry-max-attempts` | runtime default `3` | Maximum upstream retry attempts |
| `--connect-timeout-seconds` | runtime default `10` | Upstream connection timeout |
| `--anthropic-pre-upstream-concurrency` | auto `max(2, min(8, cpu_count))` | Cap simultaneous pre-upstream work on `/v1/messages` (body read, deep copy, first compression stage, memory-context lookup, upstream connect). `0` or negative disables (unbounded); any positive integer is honoured verbatim. Prevents cold-start replay storms from starving `/livez`, `/readyz`, and new Codex WS opens. |
| `--anthropic-pre-upstream-acquire-timeout-seconds` | `15.0` | Fail fast when the Anthropic pre-upstream queue is saturated. Requests that wait longer return `503` with `Retry-After` instead of parking indefinitely. |
| `--anthropic-pre-upstream-memory-context-timeout-seconds` | `2.0` | Fail-open timeout for Anthropic memory-context lookup while the request still holds a pre-upstream slot. |
| `--log-file` | unset | JSONL log output path |
| `--budget` | unset | Daily USD budget limit |
| `--no-code-aware` | off | Disable AST-aware code compression |
| `--code-aware` | off | Enable code-aware compression in the proxy (env: COPIUM_CODE_AWARE_ENABLED) |
| `--no-read-lifecycle` | off | Disable stale/superseded read compression |
| `--no-intelligent-context` | off | Disable intelligent context manager |
| `--no-intelligent-scoring` | off | Disable multi-factor importance scoring |
| `--no-compress-first` | off | Disable deep compression before dropping messages |
| `--memory` | off | Enable persistent user memory |
| `--memory-db-path` | `""` | Override memory DB path (help text: `{cwd}/.copium/memory.db`) |
| `--no-memory-tools` | off | Disable automatic memory tool injection |
| `--no-memory-context` | off | Disable automatic memory context injection |
| `--memory-top-k` | `10` | Number of memories to inject |
| `--learn` | off | Enable live traffic learning |
| `--no-learn` | off | Explicitly disable traffic learning |
| `--backend` | `anthropic` | Backend: `anthropic`, `bedrock`, `openrouter`, `anyllm`, or `litellm-*` |
| `--anyllm-provider` | `openai` | Provider name for `anyllm` |
| `--anthropic-api-url` | unset | Custom Anthropic passthrough API URL |
| `--openai-api-url` | unset | Custom OpenAI passthrough API URL |
| `--gemini-api-url` | unset | Custom Gemini passthrough API URL |
| `--region` | `us-west-2` | Cloud region for Bedrock / Vertex / related backends |
| `--bedrock-region` | unset | Deprecated Bedrock region override |
| `--bedrock-profile` | unset | AWS profile name for Bedrock |
| `--no-telemetry` | off | Disable anonymous usage telemetry |

Notes:

- `--learn` implies memory unless `--no-learn` is also set.
- Proxy startup can also read environment variables such as `COPIUM_HOST`, `COPIUM_PORT`, `COPIUM_BUDGET`, `COPIUM_MODE`, `COPIUM_ANYLLM_PROVIDER`, `COPIUM_ANTHROPIC_PRE_UPSTREAM_CONCURRENCY`, `COPIUM_ANTHROPIC_PRE_UPSTREAM_ACQUIRE_TIMEOUT_SECONDS`, `COPIUM_ANTHROPIC_PRE_UPSTREAM_MEMORY_CONTEXT_TIMEOUT_SECONDS`, `ANTHROPIC_TARGET_API_URL`, `OPENAI_TARGET_API_URL`, and `GEMINI_TARGET_API_URL`. CLI flags take precedence over environment variables.
- The default Anthropic pre-upstream cap is intentionally conservative for CPU/ONNX-heavy work. Larger containers may want to raise it after checking the resolved runtime values on `/readyz` or `/debug/warmup`.

See also: [Proxy Server](proxy.md), [Configuration](configuration.md)

## `copium learn`

Learn from past tool-call failures and produce agent guidance.

```bash
copium learn
copium learn --apply
copium learn --agent codex --all
```

| Option | Default | Meaning |
|---|---|---|
| `--project` | current project resolution | Target project path |
| `--all` | off | Analyze all discovered projects |
| `--apply` | off | Write recommendations instead of dry-run output |
| `--agent` | `auto` | Agent source: `auto`, built-ins (`claude`, `codex`, `gemini`), or plugin-provided names |
| `--model` | auto-detect | LLM model used for analysis |

Notes:

- `--agent auto` scans all detected agent data sources.
- If `--project` is omitted, Copium resolves from the current directory upward.
- External agent integrations register through the `copium.learn_plugin` entry point.

See also: [Failure Learning](learn.md)

## `copium perf`

Summarize recent proxy performance from the local proxy log.

```bash
copium perf
copium perf --hours 24
copium perf --raw
```

| Option | Default | Meaning |
|---|---|---|
| `--hours` | `168.0` | Time window in hours |
| `--raw` | off | Print raw PERF records instead of the summarized report |

The command reads `${COPIUM_WORKSPACE_DIR}/logs/proxy.log` (defaults
to `~/.copium/logs/proxy.log` — see the
[Filesystem Contract](filesystem-contract.md)).

## `copium evals`

Memory evaluation command group.

### `copium evals memory`

Run the LoCoMo memory evaluation benchmark.

```bash
copium evals memory -n 3
copium evals memory --answer-model gpt-4o --llm-judge
```

| Option | Default | Meaning |
|---|---|---|
| `--n-conversations`, `-n` | all available | Number of conversations to evaluate |
| `--categories` | benchmark default | Comma-separated categories |
| `--include-adversarial` | off | Include category 5 / unanswerable questions |
| `--top-k` | `10` | Memories retrieved per question |
| `--f1-threshold` | `0.5` | Threshold for correctness |
| `--answer-model` | unset | Model for answer generation |
| `--llm-judge` | off | Use LLM-as-judge scoring |
| `--judge-provider` | `litellm` | Judge provider: `openai`, `anthropic`, `litellm`, `simple` |
| `--judge-model` | `gpt-4o` | Judge model |
| `--output`, `-o` | unset | Save JSON results to a path |
| `--no-extract` | off | Disable LLM memory extraction |
| `--extraction-model` | `gpt-4o-mini` | Memory extraction model |
| `--pass-all` | off | Require all checks to pass |
| `--parallel` | `10` | Parallel worker count |
| `--debug` | off | Enable debug output |

### `copium evals memory-v2`

Run the V2 memory evaluation flow with LLM-controlled tools.

```bash
copium evals memory-v2
copium evals memory-v2 --save-model gpt-4o-mini --llm-judge
```

| Option | Default | Meaning |
|---|---|---|
| `--n-conversations`, `-n` | all available | Number of conversations to evaluate |
| `--categories` | benchmark default | Comma-separated categories |
| `--include-adversarial` | off | Include adversarial questions |
| `--f1-threshold` | `0.5` | Threshold for correctness |
| `--save-model` | `gpt-4o-mini` | Model used when persisting memories |
| `--answer-model` | `gpt-4o` | Answer model |
| `--max-results` | `10` | Maximum tool results |
| `--no-graph` | off | Disable graph usage |
| `--llm-judge` | off | Use LLM-as-judge scoring |
| `--judge-model` | `gpt-4o` | Judge model |
| `--output`, `-o` | unset | Save JSON results |
| `--parallel` | `5` | Parallel worker count |
| `--debug` | off | Enable debug output |

Hidden compatibility shims exist for older command paths:

- `copium memory-eval`
- `copium memory-eval-v2`

These are intentionally omitted from normal usage docs.

## `copium memory`

Memory management command group. This group is only registered when the optional memory dependencies import successfully.

### `copium memory list`

```bash
copium memory list
copium memory list --scope USER --since 7d
copium memory list -q "budget"
```

| Option | Default | Meaning |
|---|---|---|
| `--db-path` | `copium_memory.db` | Memory database path |
| `--limit`, `-n` | `50` | Maximum memories to show |
| `--session`, `-s` | unset | Filter by session ID |
| `--scope` | unset | `USER`, `SESSION`, `AGENT`, or `TURN` |
| `--since` | unset | Age filter using duration syntax such as `7d`, `2w`, `1m` |
| `--search`, `-q` | unset | Content search query |

### `copium memory show <memory_id>`

```bash
copium memory show 1234abcd
copium memory show 1234abcd --json
```

| Argument / option | Default | Meaning |
|---|---|---|
| `memory_id` | required | Full or partial memory ID |
| `--db-path` | `copium_memory.db` | Memory database path |
| `--json` | off | Emit raw JSON |

### `copium memory stats`

```bash
copium memory stats
```

| Option | Default | Meaning |
|---|---|---|
| `--db-path` | `copium_memory.db` | Memory database path |

### `copium memory edit <memory_id>`

```bash
copium memory edit 1234abcd --content "Updated note"
copium memory edit 1234abcd --importance 0.9
```

| Argument / option | Default | Meaning |
|---|---|---|
| `memory_id` | required | Full or partial memory ID |
| `--db-path` | `copium_memory.db` | Memory database path |
| `--content`, `-c` | unset | New memory content |
| `--importance`, `-i` | unset | New importance score (`0.0` to `1.0`) |

At least one of `--content` or `--importance` is required.

### `copium memory delete <memory_ids...>`

```bash
copium memory delete 1234abcd 5678efgh
copium memory delete 1234abcd --force
```

| Argument / option | Default | Meaning |
|---|---|---|
| `memory_ids...` | required | One or more memory IDs |
| `--db-path` | `copium_memory.db` | Memory database path |
| `--force`, `-f` | off | Skip confirmation |

### `copium memory prune`

```bash
copium memory prune --older-than 30d --dry-run
copium memory prune --scope SESSION --force
```

| Option | Default | Meaning |
|---|---|---|
| `--db-path` | `copium_memory.db` | Memory database path |
| `--older-than` | unset | Age threshold |
| `--scope` | unset | Scope filter: `USER`, `SESSION`, `AGENT`, `TURN` |
| `--low-importance` | unset | Importance cutoff |
| `--session`, `-s` | unset | Session ID filter |
| `--dry-run` | off | Show what would be removed |
| `--force`, `-f` | off | Skip confirmation |

At least one filter is required. Filters combine with **AND** semantics.

### `copium memory purge`

```bash
copium memory purge --confirm
```

| Option | Default | Meaning |
|---|---|---|
| `--db-path` | `copium_memory.db` | Memory database path |
| `--confirm` | off | Required confirmation flag |

### `copium memory export`

```bash
copium memory export
copium memory export --output export.json
```

| Option | Default | Meaning |
|---|---|---|
| `--db-path` | `copium_memory.db` | Memory database path |
| `--output`, `-o` | stdout | Output path |

### `copium memory import <file>`

```bash
copium memory import export.json
copium memory import export.json --force
```

| Argument / option | Default | Meaning |
|---|---|---|
| `file` | required | JSON file containing exported memories |
| `--db-path` | `copium_memory.db` | Memory database path |
| `--force`, `-f` | off | Skip confirmation |

The import expects a JSON array. Malformed entries are skipped.

## `copium mcp`

Manage the Copium MCP server integration.

### `copium mcp install`

```bash
copium mcp install
copium mcp install --proxy-url http://127.0.0.1:9000
```

| Option | Default | Meaning |
|---|---|---|
| `--proxy-url` | `http://127.0.0.1:8787` | Proxy URL written into MCP config |
| `--force` | off | Overwrite an existing Copium MCP config |

### `copium mcp uninstall`

```bash
copium mcp uninstall
```

This removes the Copium MCP server entry from the Claude configuration.

### `copium mcp status`

```bash
copium mcp status
```

This inspects MCP SDK availability, Claude config state, and proxy reachability.

### `copium mcp serve`

```bash
copium mcp serve
copium mcp serve --proxy-url http://127.0.0.1:9000 --debug
```

| Option | Default | Meaning |
|---|---|---|
| `--proxy-url` | `http://127.0.0.1:8787` | Proxy URL (also reads `COPIUM_PROXY_URL`) |
| `--direct` | off | Disable stdio transport wrapping |
| `--debug` | off | Enable debug logging |

`serve` is part of the public CLI, but it is usually consumed by MCP host tooling rather than by humans directly.

See also: [MCP Tools](mcp.md)

## `copium install`

Install and manage persistent local Copium deployments.

### `copium install apply --help`

```text
Usage: copium install apply [OPTIONS]

  Install a persistent Copium deployment.

Options:
  --preset [persistent-service|persistent-task|persistent-docker]
                                  Persistent runtime preset to install.
                                  [default: persistent-service]
  --runtime [python|docker]       Runtime used to execute Copium for
                                  service/task modes.  [default: python]
  --scope [provider|user|system]  Where to apply persistent configuration.
                                  [default: user]
  --providers [auto|all|manual]   Target selection mode for direct tool
                                  configuration.  [default: auto]
  --target [claude|copilot|codex|aider|cursor|openclaw]
                                  Tool target to configure when --providers
                                  manual is used.
  --profile TEXT                  Deployment profile name.  [default: default]
  -p, --port INTEGER              Persistent proxy port.  [default: 8787]
  --backend TEXT                  Proxy backend for the persistent runtime.
                                  [default: anthropic]
  --anyllm-provider TEXT          Provider for any-llm backends when --backend
                                  anyllm is used.
  --region TEXT                   Cloud region for Bedrock / Vertex style
                                  backends.
  --mode TEXT                     Proxy optimization mode.  [default: token]
  --memory                        Enable persistent memory in the proxy runtime.
  --no-telemetry                  Disable anonymous telemetry in the runtime.
  --image TEXT                    Docker image to use when runtime=docker or
                                  preset=persistent-docker.  [default:
                                  ghcr.io/iKislay/copium:latest]
  -?, --help                      Show this message and exit.
```

### `copium install apply`

```bash
copium install apply --preset persistent-service --providers auto
copium install apply --preset persistent-task --providers manual --target claude --target codex
copium install apply --preset persistent-docker --scope user
```

| Option | Default | Meaning |
|---|---|---|
| `--preset` | `persistent-service` | Lifecycle preset: `persistent-service`, `persistent-task`, or `persistent-docker` |
| `--runtime` | `python` | Runtime used for service/task installs: `python` or `docker` |
| `--scope` | `user` | Config scope: `provider`, `user`, or `system` |
| `--providers` | `auto` | Target selection mode: `auto`, `all`, or `manual` |
| `--target` | repeatable | Tool target used with `--providers manual` |
| `--profile` | `default` | Deployment profile name |
| `--port`, `-p` | `8787` | Persistent proxy port |
| `--backend` | `anthropic` | Backend for the managed runtime |
| `--anyllm-provider` | unset | Provider name used with `--backend anyllm` |
| `--region` | unset | Cloud region override |
| `--mode` | `token` | Proxy optimization mode |
| `--memory` | off | Enable persistent memory in the managed runtime |
| `--no-telemetry` | off | Disable anonymous telemetry |
| `--image` | `ghcr.io/iKislay/copium:latest` | Docker image for Docker-backed installs |

`apply` stores a manifest under
`${COPIUM_WORKSPACE_DIR}/deploy/<profile>/manifest.json` (default
`~/.copium/deploy/<profile>/manifest.json`), applies managed tool
configuration, starts the chosen runtime, and waits for `readyz`.

Docker-native host wrappers expose a narrower `copium install` subset for `persistent-docker` only: `apply`, `status`, `start`, `stop`, `restart`, and `remove`. Those wrapper flows preserve the same port and manifest behavior, but they intentionally reject `persistent-service`, `persistent-task`, and provider mutation flags like `--scope`, `--providers`, and `--target`.

### `copium install status`

```bash
copium install status
copium install status --profile default
```

Shows the stored profile, preset, runtime, supervisor kind, scope, port, runtime status, readiness, and backend from `/health`.

### `copium install start`

```bash
copium install start
copium install start --profile default
```

Starts a previously installed deployment profile without reapplying mutations.

### `copium install stop`

```bash
copium install stop
```

Stops the managed runtime for an installed deployment profile.

### `copium install restart`

```bash
copium install restart
```

Stops and starts the selected deployment profile.

### `copium install remove`

```bash
copium install remove
```

Stops the runtime, removes installed supervisor artifacts, reverts managed configuration changes, and deletes the stored manifest.

See also: [Persistent Installs](persistent-installs.md)

## `copium wrap`

Wrap external coding tools so their traffic flows through Copium.

### Shared semantics

- `--port`, when available, defaults to `8787`
- `--no-proxy` skips proxy startup and assumes an existing proxy
- `--learn` enables live traffic learning
- `-v`, `--verbose` means **verbose output**
- Hidden `--prepare-only` exists for internal Docker-native bridge flows and is intentionally omitted from normal usage

### `copium wrap claude`

```bash
copium wrap claude
copium wrap claude --resume <session-id>
copium wrap claude --port 9999
```

| Option / arg | Default | Meaning |
|---|---|---|
| `--port`, `-p` | `8787` | Proxy port |
| `--no-rtk` | off | Skip `rtk` installation and hook registration |
| `--no-proxy` | off | Reuse an existing proxy |
| `--learn` | off | Enable live traffic learning |
| `--verbose`, `-v` | off | Verbose output |
| `claude_args...` | passthrough | Additional Claude Code arguments |

Requires the `claude` binary on the host.

### `copium wrap codex`

```bash
copium wrap codex
copium wrap codex -- "fix the bug"
copium wrap codex --backend anyllm --anyllm-provider groq
```

| Option / arg | Default | Meaning |
|---|---|---|
| `--port`, `-p` | `8787` | Proxy port |
| `--no-rtk` | off | Skip `rtk` installation and `AGENTS.md` injection |
| `--no-proxy` | off | Reuse an existing proxy |
| `--learn` | off | Enable live traffic learning |
| `--backend` | unset | Proxy backend override |
| `--anyllm-provider` | unset | `anyllm` provider override |
| `--region` | unset | Cloud region override |
| `--verbose`, `-v` | off | Verbose output |
| `codex_args...` | passthrough | Additional Codex CLI arguments |

Requires the `codex` binary on the host.

### `copium wrap copilot`

```bash
copium wrap copilot -- --model claude-sonnet-4-20250514
copium wrap copilot --backend anyllm --anyllm-provider groq -- --model gpt-4o
```

| Option / arg | Default | Meaning |
|---|---|---|
| `--port`, `-p` | `8787` | Proxy port |
| `--no-rtk` | off | Skip `rtk` installation and GitHub Copilot instructions injection |
| `--no-proxy` | off | Reuse an existing proxy |
| `--learn` | off | Enable live traffic learning |
| `--backend` | unset | Proxy backend override |
| `--anyllm-provider` | unset | `anyllm` provider override |
| `--region` | unset | Cloud region override |
| `--provider-type` | `auto` | Force Copilot BYOK provider type (`anthropic` or `openai`) |
| `--wire-api` | unset | OpenAI wire API override for OpenAI-style backends |
| `--verbose`, `-v` | off | Verbose output |
| `copilot_args...` | passthrough | Additional Copilot CLI arguments |

Requires the `copilot` binary on the host. When a matching persistent deployment exists on the requested port, `wrap copilot` reuses or recovers it before falling back to an ephemeral proxy.

### `copium wrap aider`

```bash
copium wrap aider
copium wrap aider -- --model gpt-4o
copium wrap aider --backend litellm-vertex --region us-central1
```

| Option / arg | Default | Meaning |
|---|---|---|
| `--port`, `-p` | `8787` | Proxy port |
| `--no-rtk` | off | Skip `rtk` installation and `CONVENTIONS.md` injection |
| `--no-proxy` | off | Reuse an existing proxy |
| `--learn` | off | Enable live traffic learning |
| `--backend` | unset | Proxy backend override |
| `--anyllm-provider` | unset | `anyllm` provider override |
| `--region` | unset | Cloud region override |
| `--verbose`, `-v` | off | Verbose output |
| `aider_args...` | passthrough | Additional Aider arguments |

Requires the `aider` binary on the host.

### `copium wrap cursor`

```bash
copium wrap cursor
copium wrap cursor --port 9999
copium wrap cursor --no-rtk
```

| Option | Default | Meaning |
|---|---|---|
| `--port`, `-p` | `8787` | Proxy port |
| `--no-rtk` | off | Skip `rtk` installation and `.cursorrules` injection |
| `--no-proxy` | off | Reuse an existing proxy |
| `--learn` | off | Enable live traffic learning |
| `--verbose`, `-v` | off | Verbose output |

This command prints Cursor configuration instructions and waits while the proxy stays up. It does **not** launch Cursor directly.

### `copium wrap openclaw`

```bash
copium wrap openclaw
copium wrap openclaw --plugin-path ./plugins/openclaw
```

| Option | Default | Meaning |
|---|---|---|
| `--plugin-path` | unset | Local plugin source directory |
| `--plugin-spec` | `copium-ai/openclaw` | NPM plugin spec |
| `--skip-build` | off | Skip local `npm install` / build steps |
| `--copy` | off | Copy plugin instead of linked install |
| `--proxy-port` | `8787` | Copium proxy port |
| `--startup-timeout-ms` | `20000` | Proxy startup timeout |
| `--gateway-provider-id` | repeatable | OpenClaw provider IDs routed through Copium |
| `--python-path` | unset | Python launcher override |
| `--no-auto-start` | off | Disable plugin auto-start behavior |
| `--no-restart` | off | Do not restart the OpenClaw gateway |
| `--verbose`, `-v` | off | Verbose output |

Requires the `openclaw` binary on the host, and local-source mode may also require `npm`. In Docker-native mode, the installed host wrapper drives the host `openclaw` CLI while the plugin auto-starts the host `copium` wrapper from `PATH`.

## `copium unwrap`

Undo durable wrapping for supported tools.

### `copium unwrap openclaw`

```bash
copium unwrap openclaw
copium unwrap openclaw --no-restart
```

| Option | Default | Meaning |
|---|---|---|
| `--no-restart` | off | Do not restart the OpenClaw gateway |
| `--verbose`, `-v` | off | Verbose output |

This disables the Copium OpenClaw plugin and restores the legacy context engine slot.

## Docker-native parity matrix

This matrix compares the **Python CLI contract** to the Docker-native host wrapper added in this branch.

Legend:

- **native in container** — the command runs entirely inside the Copium container
- **host-bridged** — Copium runs in Docker, but the wrapped external tool still runs on the host

| Command path | Python CLI | Docker-native wrapper | Parity |
|---|---|---|---|
| `copium proxy` | native | native in container | full |
| `copium learn` | native | native in container | full |
| `copium perf` | native | native in container | full |
| `copium evals memory` | native | native in container | full |
| `copium evals memory-v2` | native | native in container | full |
| `copium memory ...` | native (when memory deps are available) | native in container | full |
| `copium mcp install` | native | native in container | full |
| `copium mcp uninstall` | native | native in container | full |
| `copium mcp status` | native | native in container | full |
| `copium mcp serve` | native | native in container | full |
| `copium install apply|status|start|stop|restart|remove` | native | Docker-native wrapper for `persistent-docker`; compose remains an alternative | partial |
| `copium wrap claude` | native | host-bridged | partial |
| `copium wrap copilot` | native | not implemented in Docker-native wrapper | none |
| `copium wrap codex` | native | host-bridged | partial |
| `copium wrap aider` | native | host-bridged | partial |
| `copium wrap cursor` | native | host-bridged | partial |
| `copium wrap openclaw` | native | host-bridged | partial |
| `copium unwrap openclaw` | native | host-bridged | partial |

For the Docker-native execution model itself, see [Docker-Native Install](docker-install.md). For persistent service/task/docker lifecycle management, see [Persistent Installs](persistent-installs.md).

## Hidden and compatibility-only command paths

These exist in code but are intentionally excluded from normal user docs:

- `copium memory-eval`
- `copium memory-eval-v2`
- hidden internal `--prepare-only` flags on `wrap` subcommands

If you are documenting operational behavior or debugging internal wrapper flows, refer to the implementation in `copium/cli/wrap.py`.
