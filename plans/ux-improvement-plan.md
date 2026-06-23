# Copium UX Improvement Plan

> Status: Draft · Author: Kislay · Date: 2026-06-23

This document is a deep, end-to-end audit of the Copium developer experience. It covers every touchpoint a developer encounters — from first hearing about the tool, to daily use, to recommending it to a teammate. The goal is to make Copium feel as polished as tools like `gh`, `starship`, or `uv`: zero-friction, fully transparent, and impossible to get wrong.

---

## 1. The Problem With the Current Experience

Before listing improvements, we need to be honest about friction points:

| Friction Point | Impact |
|---|---|
| User must manually set `ANTHROPIC_BASE_URL` / `OPENAI_API_BASE` and keep it across shell sessions | High friction — most devs forget this on every new terminal |
| No feedback loop: proxy runs silently, no indication it's working | Dev doesn't know if it's actually intercepting requests |
| Dashboard lives at port 8787 — most devs won't open a browser just to check savings | Low adoption of the most compelling feature |
| `copium run` blocks the terminal or must be backgrounded manually | Annoying in daily workflow |
| No shell completion | Makes CLI feel unpolished |
| First time setup: 4+ manual steps (install, run, set env var, verify) | Too many steps to trust a new tool |
| Global vs. project-level config is ambiguous | Confusing for new users |
| No way to see if Copium is active from inside a running agent | Dev must check externally |
| Uninstall is undocumented | Creates trust issues ("how do I get rid of this?") |

---

## 2. Distribution & Global Install

### 2a. PyPI (Already live — improve discoverability)

The package `copium-ai` on PyPI is the right call. Key improvements:

- **Better package name exposure**: The README should prominently show `pipx install copium-ai` as the recommended install method (not `pip install`). `pipx` installs CLI tools into isolated envs and makes the `copium` binary available globally without polluting any project.
- **uv tool install** should be the first option shown (it already is in README — good). Both should be in a prominent "Install" section at the very top.
- **PyPI classifiers**: Ensure `pyproject.toml` has `Topic :: Software Development :: Libraries :: Python Modules`, `Environment :: Console`, and `Intended Audience :: Developers`. This boosts search ranking on PyPI.
- **Entry point hygiene**: Confirm the `copium` binary is the only entry point. Don't leak internal subcommands as separate binaries.

```bash
# Recommended install (show these first in README, before anything else)
pipx install copium-ai          # globally, isolated env
uv tool install copium-ai       # globally, if using uv
pip install "copium-ai[proxy]"  # project-specific (less recommended for CLI use)
```

### 2b. Homebrew Tap

Create a `homebrew-copium` tap repo (`github.com/iKislay/homebrew-copium`). This unlocks:

```bash
brew tap ikislay/copium
brew install copium
```

Many devs (especially macOS) reach for `brew` first. A tap repo with a simple formula pointing to the PyPI wheel (or a binary release) covers this case. No complex packaging needed — a Python-based formula works.

### 2c. Shell Installer Script (Like `rustup`, `gh`, `starship`)

Create `install.sh` hosted at `copium.sh` or `get.copium.dev`:

```bash
curl -fsSL https://get.copium.dev | sh
```

This script:
1. Detects OS/arch
2. Checks for `uv`, `pipx`, `pip` in order of preference
3. Installs using the best available method
4. Runs `copium doctor` at the end to verify

This is the fastest possible path to a working install. One command, zero decisions.

### 2d. Binary Releases (GitHub Actions)

Since the core logic is in Rust (`crates/`), build pre-compiled binaries for:
- `linux-x86_64`, `linux-aarch64`
- `macos-x86_64`, `macos-aarch64` (Apple Silicon)
- `windows-x86_64`

Publish to GitHub Releases. Add download links to README. This removes the Python dependency entirely for users who just want the proxy.

```bash
# Without Python
curl -Lo copium https://github.com/iKislay/copium/releases/latest/download/copium-linux-x86_64
chmod +x copium && sudo mv copium /usr/local/bin/
```

---

## 3. Onboarding: The First 60 Seconds

The current README says "Get started (60 seconds)" but that's optimistic — it takes longer because of the env var step. Here's how to actually get to 60 seconds.

### 3a. `copium init` — The Missing Command

This is the single biggest UX win available. One guided setup command that works for any tool:

```bash
copium init
```

Flow:
1. **Detect installed agents** — scan PATH for `claude`, `cursor`, `aider`, `opencode`, `codex`, etc.
2. **Show a numbered menu** (or auto-select if only one):
   ```
   Copium detected the following AI agents on your system:
   
     [1] Claude Code  (claude)
     [2] OpenCode     (opencode)
     [3] Aider        (aider)
   
   Select agents to wrap [1,2,3 or 'all']: _
   ```
3. **Patch shell rc files** — write `export ANTHROPIC_BASE_URL=http://localhost:8082` to `~/.zshrc` / `~/.bashrc` / `~/.config/fish/config.fish` depending on the user's shell, with a clearly labeled comment block:
   ```bash
   # >>> copium start <<<
   export ANTHROPIC_BASE_URL=http://localhost:8082
   export OPENAI_API_BASE=http://localhost:8082/v1
   # >>> copium end <<<
   ```
4. **Create `~/.copium/config.toml`** global config (see section 5)
5. **Optionally install as a launch agent** (macOS `launchd` / Linux `systemd --user`) so the proxy auto-starts on login (see section 4)
6. **Confirm and print next steps**:
   ```
   ✓ Shell config updated (~/.zshrc)
   ✓ Global config written (~/.copium/config.toml)
   ✓ Proxy set to auto-start on login
   
   Reload your shell with: source ~/.zshrc
   Then run: claude  (Copium will be active automatically)
   
   View savings at any time: copium status
   ```

### 3b. `copium remove` / `copium uninstall` — Documented Clean Removal

Every dev tool needs a clean uninstall path. Right now this is undocumented. Add:

```bash
copium remove
```

This:
1. Removes the `# >>> copium start <<<` block from all detected rc files
2. Removes `~/.copium/` data directory (with confirmation prompt)
3. Unregisters any launch agents / systemd units
4. Prints: `Copium has been fully removed. Your original agent settings have been restored.`

Trust comes from knowing you can easily undo something.

---

## 4. The "Always On" Problem — Background Service Mode

The biggest daily friction: `copium run` blocks your terminal. Developers solve this with `copium run &`, but then it dies when the terminal closes.

### 4a. `copium start` / `copium stop` (Daemon Mode)

```bash
copium start    # start as background daemon, detach from terminal
copium stop     # gracefully stop the daemon
copium restart  # restart (picks up config changes)
copium status   # show if running, uptime, port, tokens saved today
```

`copium start` writes a PID file to `~/.copium/copium.pid`. Logs go to `~/.copium/logs/copium.log`. The proxy runs detached. `copium stop` reads the PID and sends SIGTERM.

This is how `nginx`, `redis-server`, and `postgresql` all work. It's the expected pattern for a server process.

### 4b. System Service Integration

For users who want the proxy available immediately after login (before they even open a terminal):

```bash
copium service install   # install as systemd unit (Linux) or launchd plist (macOS)
copium service remove    # uninstall the service
copium service status    # show service health
copium service logs      # tail the service logs
```

**Linux (systemd user unit)**:
```ini
[Unit]
Description=Copium context compression proxy
After=network.target

[Service]
ExecStart=/home/<user>/.local/bin/copium run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

**macOS (launchd plist)** — written to `~/Library/LaunchAgents/dev.copium.plist`.

This means developers never have to think about starting Copium. It's just always there.

---

## 5. Global vs. Project Config — Clear Mental Model

Right now users can create `copium.json` in a project root, but global config is undocumented. Establish a clear two-tier hierarchy:

```
~/.copium/config.toml         Global defaults (always loaded)
<project-root>/copium.json    Project overrides (loaded if present)
```

Project config wins on any key that both specify. This is the same model as `.gitconfig` (global) + `.git/config` (repo).

**Global config (`~/.copium/config.toml`)**:
```toml
[proxy]
port = 8082
host = "127.0.0.1"

[compression]
preset = "standard"
quality_gate = true

[dashboard]
port = 8787
open_on_start = false

[telemetry]
enabled = false   # opt-in only
```

**`copium config`** command — inspect and edit config from CLI:

```bash
copium config                          # show full resolved config (global + project merged)
copium config --global                 # show only global config
copium config set compression.preset aggressive   # edit a key
copium config set --global proxy.port 9090        # edit global config
copium config reset                    # reset to defaults
copium config path                     # print the config file path
```

This mirrors `git config`, `npm config`, and `gh config` — patterns developers already know.

---

## 6. CLI UX — Command Design

### 6a. Full Command Surface (proposed)

```
copium init                   Guided first-time setup
copium start                  Start proxy as background daemon
copium stop                   Stop the daemon
copium restart                Restart the daemon
copium status                 Show proxy health, uptime, savings
copium wrap <agent>           Configure an agent to use Copium
copium unwrap <agent>         Restore an agent's original config
copium agents                 List all detected agents and their wrap status

copium dashboard              Open/show the web dashboard
copium tui                    Launch the terminal UI dashboard
copium stats                  Show compression statistics summary
copium stats --session        Stats for current session only
copium stats --json           Machine-readable output

copium config                 Show resolved config
copium config set <k> <v>     Set a config value
copium config --global        Operate on global config
copium config reset           Reset to defaults
copium config path            Show config file location

copium preset <name>          Show what a preset does (no side effects)
copium preset list            List all available presets

copium doctor                 Diagnose your setup (LLM detection, port conflicts, etc.)
copium logs                   Tail proxy logs
copium logs --tail 100        Last N lines

copium service install        Install as system service
copium service remove         Uninstall system service
copium service status         Show service health
copium service logs           Tail service logs

copium remove                 Fully remove Copium (config, env vars, services)
copium update                 Update to latest version
copium version                Print version
copium help [command]         Help for any command
```

### 6b. Output Formatting

Every command should follow a consistent output style:

- **Colors**: Use green `✓` for success, yellow `⚠` for warnings, red `✗` for errors. Use ANSI only when stdout is a TTY; strip colors for piped output.
- **Structured**: All commands that output data support `--json` flag for scripting.
- **Quiet mode**: All commands support `--quiet` / `-q` to suppress non-error output. Good for scripts and CI.
- **Verbose mode**: `--verbose` / `-v` shows debug-level info (transform decisions, cache hits, etc.).

Example of `copium status` output:
```
● Copium is running  (pid 12345, port 8082, uptime 4h 23m)

  Today's savings
  ───────────────
  Requests proxied      247
  Tokens saved          312,481  (avg 38% per request)
  Estimated cost saved  $0.94

  Active session (claude, last seen 2m ago)
  Tokens saved          48,219  (62% compression)

  Config:  ~/.copium/config.toml
  Logs:    ~/.copium/logs/copium.log
  Dashboard: http://localhost:8787/dashboard
```

### 6c. Shell Completion

Generate completion scripts for all major shells:

```bash
copium completion bash   >> ~/.bash_completion
copium completion zsh    >> ~/.zshrc
copium completion fish   > ~/.config/fish/completions/copium.fish
copium completion powershell
```

This should be auto-suggested at the end of `copium init`. Tab completion on subcommands and flags makes the tool feel professional.

---

## 7. Terminal UI (TUI) Dashboard

The web dashboard is great for initial exploration but most devs live in the terminal. A TUI (built with `ratatui` — already a Rust crate in the ecosystem) gives an always-visible live view.

```bash
copium tui
```

### Layout (80-column terminal)

```
╭─ Copium ─────────────────────────────────────────────── v0.9.0 ● Running ─╮
│                                                                              │
│  SESSION ─────────────────────────────  ALL TIME ──────────────────────── │
│  Agent:     Claude Code                 Tokens saved:    1.4B               │
│  Duration:  1h 42m                      Sessions:        50,412              │
│  Tokens in: 284,312                     Avg compression: 38%                │
│  Saved:     141,203 (49.7%)             Est. saved:      $4,218              │
│  Cost saved: ~$0.42                                                          │
│                                                                              │
│  TRANSFORMS ──────────────────────────────────────────────────────────────  │
│  SmartCrusher    ████████████████░░░░  82%   12 hits                        │
│  Session Dedup   ████████████░░░░░░░░  61%    8 hits                        │
│  TOON Encoder    ██████░░░░░░░░░░░░░░  31%    5 hits                        │
│  Error Compres.  █████████████████░░░  87%    3 hits                        │
│  Cache Aligner   ████░░░░░░░░░░░░░░░░  20%   all requests                  │
│                                                                              │
│  LIVE REQUESTS ────────────────────────────────────────────────────────── │
│  12:04:31  POST /v1/messages   in:4812  out:892   saved:81.5%  SmartCrush  │
│  12:04:28  POST /v1/messages   in:1204  out:947   saved:21.3%  CacheAlign  │
│  12:04:21  POST /v1/messages   in:8341  out:1203  saved:85.6%  SessionDed  │
│  12:04:15  POST /v1/messages   in:2103  out:1891  saved: 9.9%  Passthru    │
│                                                                              │
│  [q] quit  [p] pause  [r] reset session  [c] config  [?] help              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Key features:
- Real-time updates (100ms refresh)
- Per-transform breakdown with bar charts
- Live request stream showing which transform fired
- Keyboard shortcuts for common actions
- Works in any 80+ column terminal
- No network dependency (reads from local proxy socket)

---

## 8. Transparency Layer — "Show Your Work"

Developers don't trust black boxes. Copium's biggest trust problem is that it's invisible. Solve this with a transparency layer:

### 8a. `copium explain <request-id>`

Every proxied request gets a short ID (shown in the TUI live feed). The developer can inspect exactly what happened:

```bash
copium explain req_7f3a2b
```

Output:
```
Request req_7f3a2b — POST /v1/messages — 12:04:31

Input
  Original:   4,812 tokens
  Compressed: 892 tokens  (81.5% saved)

Transforms applied (in order)
  1. ContentRouter    → detected JSON array (500 items), routed to SmartCrusher
  2. SmartCrusher     → 500 items → 23 items (BM25 + variance selection)
                        CCR hash: sha256:8f3a... stored for retrieval
  3. CacheAligner     → moved session_id to suffix (prefix stabilized)
  4. TOON Encoder     → skipped (not a uniform-structure array)

Quality check
  ✓ No inflation detected (892 < 4812)
  ✓ Critical markers preserved (errors, warnings: 3/3)
  ✓ CCR index written to ~/.copium/ccr/req_7f3a2b.bin

Retrieve original at any time:
  copium retrieve req_7f3a2b
```

### 8b. Inline `X-Copium-*` Response Headers

Every response from the proxy includes headers the developer can inspect with `curl -i` or browser devtools:

```
X-Copium-Request-Id: req_7f3a2b
X-Copium-Tokens-In: 4812
X-Copium-Tokens-Out: 892
X-Copium-Savings: 81.5%
X-Copium-Transforms: SmartCrusher,CacheAligner
X-Copium-Overhead-Ms: 48
```

### 8c. Audit Log

Every compression decision is written to `~/.copium/logs/audit.jsonl`:

```json
{"ts":"2026-06-23T19:04:31Z","req":"req_7f3a2b","transforms":["SmartCrusher","CacheAligner"],"tokens_in":4812,"tokens_out":892,"savings":0.815,"overhead_ms":48}
```

This lets developers grep their own history, pipe to `jq`, and build their own analysis. A developer who can verify the tool is doing what it says will recommend it to teammates.

---

## 9. Active Status Indicator

Developers need to know Copium is active without switching windows. Two ideas:

### 9a. Shell Prompt Integration

Add a `copium status --prompt` command that outputs a minimal status string for shell prompts (compatible with Starship, p10k, oh-my-zsh):

```bash
# ~/.zshrc or starship.toml
# Shows: ⚡ 38% when Copium is running and compressing
```

`copium init` should offer to add this automatically.

### 9b. `copium ping`

A fast (<5ms) health check for scripts and prompt integration:

```bash
copium ping          # exit 0 if running, exit 1 if not
copium ping --json   # {"status":"running","uptime_s":15423,"tokens_saved_today":312481}
```

---

## 10. First-Time Feedback Loop — "Proof It's Working"

The moment a developer first routes a request through Copium, they should see something. Currently there's nothing unless they open the dashboard.

### 10a. First-Request Toast

After the very first request is proxied, print a one-time message to the log (and optionally to the terminal if attached):

```
🎉 First request compressed!
   Tokens: 4,812 → 892  (81.5% saved, ~$0.01 saved on this request)
   
   View live savings: copium tui
   Or open: http://localhost:8787/dashboard
```

This is a one-time message stored in `~/.copium/state.json` (`{"first_request_shown": true}`).

### 10b. Session Summary on `copium stop`

When the daemon is stopped (or `ctrl+c` in foreground mode), print a session summary:

```
Copium stopped.

Session summary (2h 14m)
─────────────────────────
Requests proxied   312
Tokens saved       421,847  (avg 44%)
Est. cost saved    $1.27
Peak compression   91.5%  (build log, 4 hits)

All-time: 1.4B tokens saved across 50,412 sessions.
```

---

## 11. Error UX

Errors should tell the developer exactly what's wrong and exactly what to do.

| Situation | Bad (current) | Good (proposed) |
|---|---|---|
| Port 8082 already in use | Python traceback | `✗ Port 8082 is in use. Try: copium start --port 8083` |
| Proxy not running when agent tries to connect | Silent failure | `⚠ Agent connected but Copium proxy is not running. Start it with: copium start` |
| Config file syntax error | No validation | `✗ Config error in ~/project/copium.json:7 — unknown key "presset". Did you mean "preset"?` |
| `copium wrap <agent>` but agent not found | Generic error | `✗ Could not find "cursor" in PATH. Install Cursor first, then run: copium wrap cursor` |

All errors should:
1. Start with `✗` in red
2. Say exactly what went wrong (not a stack trace)
3. Say exactly what to do next
4. Link to docs if the fix is non-trivial

---

## 12. `copium doctor` — Enhanced Diagnostics

Make `copium doctor` the go-to command for "something's wrong":

```bash
copium doctor
```

Checks and reports on:
- Is the proxy running? On which port?
- Is any agent currently routing through Copium? (check env vars of running processes)
- Is the configured port accessible (not firewalled/blocked)?
- Are shell rc files correctly patched?
- Is there a systemd/launchd service installed?
- Is the Rust compression core reachable?
- Local LLM: Is Ollama running? What model? What quantization? KV cache risk level?
- Is there a newer version of Copium available?
- Is the CCR store healthy (can read/write)?

Output:
```
copium doctor — system check

  ✓ Proxy running           (pid 12345, port 8082, uptime 4h 23m)
  ✓ Shell config patched    (~/.zshrc, ~/.bashrc)
  ✓ systemd service active  (auto-starts on login)
  ✓ CCR store healthy       (128 entries, 4.2 MB)
  ⚠ Ollama running          Q4_0 quantization detected — aggressive preset recommended
                            Run: copium config set compression.preset local-llm
  ⚠ New version available   0.9.1 → 0.10.0
                            Run: copium update

  2 warnings. Run `copium doctor --fix` to auto-resolve.
```

`copium doctor --fix` auto-applies all safe fixes (update preset, etc.) and asks before any destructive ones.

---

## 13. Documentation UX

### 13a. Docs Site (copium-docs.vercel.app)

- **Add a "Is it working?" page** — this is the #1 question new users have. Walk through `copium status`, the TUI, and response headers.
- **Command reference** — auto-generated from CLI help text. Always in sync.
- **Troubleshooting** — cover the top 10 questions (port conflicts, env var not set, agent not routing through proxy).
- **Interactive cost calculator** — "I run Claude Code for X hours/day with Y tool calls" → "You'd save $Z/month". Lives on the landing page.

### 13b. In-CLI Help

Every command's `--help` output should include a real example, not just a synopsis:

```bash
copium wrap --help

  Configure an AI agent to route through the Copium proxy.

  Usage:
    copium wrap <agent>

  Arguments:
    agent   One of: claude, cursor, aider, opencode, codex, copilot, cline, continue, vibe

  Examples:
    copium wrap claude          Start proxy + configure Claude Code
    copium wrap aider           Configure Aider (proxy must already be running)
    copium wrap cursor          Print Cursor configuration instructions

  Notes:
    Use `copium unwrap <agent>` to restore original configuration.
    Use `copium agents` to see the wrap status of all detected agents.

  Docs: https://copium-docs.vercel.app/docs/wrap
```

---

## 14. Upgrade Path

```bash
copium update
```

- Checks PyPI for newer version
- Shows changelog excerpt (last 3 entries from CHANGELOG.md)
- Runs `pip install --upgrade copium-ai` (or `uv tool upgrade copium-ai` if installed via uv)
- Restarts daemon if it was running

```
Updating Copium 0.9.0 → 0.10.0

  What's new:
  • TUI dashboard (copium tui)
  • copium start/stop daemon mode  
  • Shell completion for zsh/fish/bash
  See full changelog: https://github.com/iKislay/copium/releases/tag/v0.10.0

Downloading... ████████████████████ 100%
Restarting proxy...

✓ Copium 0.10.0 is running. No configuration changes needed.
```

---

## 15. CLI Polish — Hidden Commands, Progress, Help Grouping

The existing plan covers the command surface but misses several quality-of-life details that make a CLI feel professional.

### 15a. `copium --all` Flag for Hidden Commands

Advanced commands (`benchmark`, `evals`, `learn`, `audit`, `capture`, `ccr`, `tools`, `telemetry`, `mcp`, `copilot-auth`, `recipe`, `agent-savings`) clutter `--help` for individual devs. Hide them by default and show with `--all`:

```bash
$ copium --help
  Quick Start:
    init          Guided first-time setup
    start         Start proxy as background daemon
    status        Show proxy health and savings

  Agent Integration:
    wrap          Configure an agent to use Copium
    unwrap        Restore an agent's original config
    agents        List detected agents and wrap status

  Analytics:
    stats         Compression statistics
    dashboard     Open/show the web dashboard
    tui           Launch terminal UI dashboard

  Configuration:
    config        Show/edit configuration
    preset        Apply compression preset

  Operations:
    doctor        Diagnose your setup
    logs          Tail proxy logs
    service       Manage system service
    remove        Fully remove Copium
    update        Update to latest version

  Use `copium --all` to see advanced commands.

$ copium --all --help
  ... (shows everything including benchmark, evals, learn, etc.)
```

### 15b. Rich Progress Bars & Spinners

The CLI currently has no visual feedback during long operations. Add a shared `copium.cli._utils.progress` module:

```python
# copium/cli/_utils/progress.py
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.live import Live

console = Console()

def spinner(message: str):
    """Context manager that shows a spinner."""
    return Live(Text(f"  ⏳ {message}"), console=console, refresh_per_second=10)

def download_bar(description: str, total: int):
    """Returns a Rich Progress bar for downloads."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    )
```

Apply to:
- **Proxy startup**: `spinner("Starting proxy on :8787...")` with green check on success
- **RTK download**: `download_bar("Downloading RTK binary", total)` during `copium wrap`
- **`copium init`**: Step-by-step progress: `Step 1/4: Detecting agents...`
- **`copium doctor`**: Animated check sequence
- **`copium update`**: Download progress bar

### 15c. `copium completions` Command

Make shell completion setup a single command:

```bash
$ copium completions bash >> ~/.bash_completion
$ copium completions zsh >> ~/.zshrc
$ copium completions fish > ~/.config/fish/completions/copium.fish
$ copium completions powershell
```

Auto-suggest this at the end of `copium init`:

```
✓ Setup complete! Enable tab completion:
  copium completions zsh >> ~/.zshrc && source ~/.zshrc
```

### 15d. `copium --tutorial` Guided Walkthrough

An interactive tutorial for first-time users (skippable, only shown on first run):

```
$ copium --tutorial

  Welcome to Copium! Let's get you set up in 60 seconds.

  What Copium does:
  Copium compresses your LLM context (tool outputs, API responses)
  to save tokens and money. A typical developer saves 40-70% on
  token costs with zero quality loss.

  Step 1: What agent do you use?
    [1] Claude Code
    [2] OpenCode
    [3] Aider
    [4] Codex
    [5] Other / I'll configure manually
    > 1

  Step 2: Starting proxy...
    ✓ Proxy running on http://localhost:8787

  Step 3: Configuring Claude Code...
    ✓ Added ANTHROPIC_BASE_URL to ~/.zshrc
    ✓ Installed compression hooks

  Step 4: Verifying...
    ✓ Proxy is intercepting requests

  ✓ Copium is ready! Just run: claude

  View savings: copium status
  Live dashboard: copium tui
  Diagnostics: copium doctor

  Press any key to continue...
```

### 15e. `copium feedback` Command

Low-friction feedback path:

```bash
$ copium feedback

  How was your experience with Copium?
    [1] Great — saving tokens as expected
    [2] Good — works but could be better
    [3] Not working — I have an issue
    [4] Feature request
    > 1

  ✓ Thanks for the feedback! Star us on GitHub:
    https://github.com/iKislay/copium

  (For issues: https://github.com/iKislay/copium/issues)
```

### 15f. Docker Slim Image

The current Docker image is 900MB+ (includes torch/onnxruntime). Create a lightweight variant:

```dockerfile
# Dockerfile.slim
FROM python:3.11-slim AS runtime
# No torch, no onnxruntime, no ML deps
# Just the proxy + core compression
# ~200MB image size
```

```yaml
# docker-compose.slim.yml
services:
  copium:
    build:
      dockerfile: Dockerfile.slim
    ports:
      - "8787:8787"
    environment:
      - COPIUM_PORT=8787
```

Add a `copium docker` command:
```bash
$ copium docker          # start proxy in Docker with one command
$ copium docker --slim   # use lightweight image
$ copium docker stop     # stop the Docker container
```

---

## 16. Prioritization (Updated)

### Ship First (highest UX impact, lowest effort)

| Item | Why |
|---|---|
| `copium start` / `copium stop` daemon mode | Eliminates the biggest daily friction point |
| `copium status` with rich output | Instant feedback that it's working |
| Shell completion + `copium completions` command | Makes the tool feel professional immediately |
| `copium remove` | Builds trust by making it reversible |
| Response headers (`X-Copium-*`) | Transparency without any extra work from the user |
| Rich progress bars & spinners | Visual feedback during proxy startup, downloads |
| `copium --all` flag for hidden commands | Clean default help, advanced commands accessible |
| Grouped help text by category | Easier command discovery |

### Ship Next (high impact, moderate effort)

| Item | Why |
|---|---|
| `copium init` with agent detection | Best possible onboarding |
| `copium tui` terminal dashboard | Keeps devs in the terminal, not the browser |
| `copium doctor --fix` | Reduces support burden |
| Shell prompt integration | Always-visible status |
| First-request feedback message | Closes the "is it working?" loop immediately |
| `copium --tutorial` guided walkthrough | Zero-friction first experience |
| `copium feedback` command | Low-friction user feedback path |

### Ship Later (differentiation, more effort)

| Item | Why |
|---|---|
| `copium explain <id>` | Deep transparency layer |
| Homebrew tap | macOS distribution |
| Binary releases | Remove Python dependency |
| `copium update` with changelog | Quality of life |
| Session summary on stop | Satisfying feedback loop |
| `copium service install` | For power users |
| Docker slim image + `copium docker` | Container-native workflow |

---

## 17. Summary — The Target Experience

A developer hears about Copium. Here's what the ideal experience looks like:

```bash
# 1. Install (one command, works everywhere)
curl -fsSL https://get.copium.dev | sh
# OR: brew tap ikislay/copium && brew install copium
# OR: pipx install copium-ai
# OR: docker run -p 8787:8787 copium/copium

# 2. Setup (one guided command, 30 seconds)
copium init
# → detects claude + aider
# → patches ~/.zshrc
# → installs as system service
# → enables tab completion
# → prints: "Reload shell, then just run your agent normally"

# 3. Daily use (zero commands — it's just running)
claude  # Copium intercepts automatically, they see normal Claude responses

# 4. Check in occasionally
copium status     # 2-line summary of today's savings
copium tui        # when they want the full picture

# 5. Something goes wrong
copium doctor     # tells them exactly what and how to fix it
copium doctor --fix  # auto-resolves safe issues

# 6. See what Copium did
copium explain req_7f3a2b  # shows exact transformation for a request

# 7. Share with a teammate
"just run: curl -fsSL https://get.copium.dev | sh && copium init"

# 8. Uninstall if needed
copium remove     # clean, complete, no residue
```

That's the target. Every item in this plan either removes a step from that flow or makes one of those steps more trustworthy.
