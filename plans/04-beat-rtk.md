# Plan: Absorb RTK's Audience — "RTK on Steroids"

**Status:** In Progress (Phase 1 complete)
**Date:** 2026-06-22
**Updated:** 2026-06-23
**Goal:** Position Copium as the definitive RTK replacement, capturing its 28K+ GitHub stars audience by fixing every RTK limitation while keeping the one-command simplicity users love.

---

## 1. RTK's Popularity — Why People Love It

RTK succeeded because of radical simplicity. Understanding this is non-negotiable before we can absorb its users.

### 1.1 The Core Insight RTK Got Right

RTK solves one problem brilliantly: **"I type `rtk git status` instead of `git status` and save 60-90% of context tokens. That's it."**

No proxy server. No configuration file. No YAML. No learning curve. One binary, one prefix.

### 1.2 Why 28K Stars

| Factor | Detail |
|---|---|
| **Zero-config start** | `brew install rtk` → done. No API keys, no servers, no config files. |
| **Shell-native UX** | Users already know `git status`. `rtk git status` is a trivial mental model. |
| **Immediate visible savings** | `rtk git status` produces visibly shorter output. Users see the win instantly. |
| **Agent-agnostic** | Works with Claude Code, Cursor, Codex, Aider — any agent that runs shell commands. |
| **Trust through simplicity** | Users can audit what RTK does — it's just stdout rewriting. No hidden proxy behavior. |
| **Community momentum** | Star-driven discovery. "RTK saves 80% on git output" is a shareable one-liner. |

### 1.3 RTK's Actual Limitations (Our Opportunity)

These are the gaps Copium already partially or fully addresses:

| Limitation | Impact | Copium's Existing Answer |
|---|---|---|
| **CLI stdout only** | Only compresses what commands print. File reads, search results, MCP tool outputs — untouched. | Proxy intercepts ALL API traffic (tool_result blocks, not just stdout). |
| **"Strangeness tax"** | Compressed output confuses LLMs. LLMs trained on full `git status` output struggle with RTK's abbreviated format. | 37 content-aware transforms with quality gates. CCR allows retrieval of originals. |
| **No diagnostic output** | Strips stderr, warnings, non-zero exit info. LLMs miss critical error context. | Transforms preserve error signatures, stack traces, and exit codes. |
| **No file read compression** | `cat file.py` or agent Read tool calls are not compressed. | SmartCrusher, Kompress, session dedup handle file content. |
| **No search result compression** | `grep`, `ripgrep`, LSP results — only partially handled. | ContentRouter dispatches search results to specialized compressors. |
| **No reversibility** | Once output is compressed, original is gone. LLM can't request full detail. | CCR (Compress-Cache-Retrieve) stores originals for on-demand retrieval. |
| **No observability** | No metrics, no dashboards, no way to know how much was saved. | Prometheus metrics, `copium perf`, per-session savings tracking. |

---

## 2. How Copium Absorbs RTK's Audience

### 2.1 The Migration Path (Staged)

RTK users won't switch overnight. We need a staged migration that meets them where they are.

```
Stage 1: Drop-in replacement     → copium wrap claude (RTK included, zero change)
Stage 2: Discover the upgrade    → copium perf shows RTK savings + proxy savings
Stage 3: Full Copium activation  → proxy intercepts all traffic, RTK becomes one of many transforms
Stage 4: RTK sunset              → Copium's native transforms make RTK binary unnecessary
```

### 2.2 The "RTK Compatible" Promise

Every `copium wrap <agent>` command must:

1. **Include RTK by default** — RTK binary is downloaded and configured automatically (already done in `copium/rtk/installer.py:72`). RTK is vendored at a pinned version (`RTK_VERSION = "v0.28.2"` at `copium/rtk/__init__.py:15`); see `docs/rtk-architecture.md` for why RTK stays on the wrap-CLI side only.
2. **RTK instructions are injected** — The `RTK_INSTRUCTIONS_BLOCK` at `copium/cli/wrap.py:993` tells the agent to prefix commands with `rtk`.
3. **Proxy handles everything RTK doesn't** — File reads, search results, conversation history, tool_result blocks.
4. **Show combined savings** — `copium perf` reports both RTK savings (`tokens_saved_rtk`) and proxy savings in one dashboard.

### 2.3 Competitive Positioning

```
RTK:          rtk git status  → compresses CLI stdout     → 60-90% on stdout
Copium:       copium wrap claude → compresses EVERYTHING  → 40-90% on all context
              (includes RTK for stdout)
```

The pitch: "Copium includes RTK for free, plus compresses everything RTK can't reach."

---

## 3. `copium wrap` Command Improvements

### 3.1 Current State (from `copium/cli/wrap.py`)

The wrap system already supports:
- `copium wrap claude` — Proxy + RTK + Claude Code launch
- `copium wrap codex` — Proxy + RTK + Codex launch
- `copium wrap aider` — Proxy + RTK + Aider launch
- `copium wrap cursor` — Proxy + RTK + Cursor config
- `copium wrap copilot` — Proxy + RTK + Copilot launch
- `copium wrap openclaw` — Plugin installation
- `copium wrap cline` — Proxy + RTK + Cline launch (VS Code)
- `copium wrap continue` — Proxy + RTK + Continue launch (VS Code/JetBrains)
- `copium wrap goose` — Proxy + RTK + Goose launch (Block CLI)
- `copium wrap openhands` — Proxy + RTK + OpenHands launch

### 3.2 Proposed Improvements

#### 3.2.1 `copium wrap --rtk-only` Mode (New)

For users who want RTK-only compression (RTK's exact use case) without the proxy:

```bash
copium wrap claude --rtk-only
```

This:
- Downloads RTK binary
- Registers hooks / injects instructions
- Launches Claude Code
- **Does NOT start the proxy**

Purpose: Meet RTK users exactly where they are. Zero behavioral change. Then gradually introduce proxy features.

#### 3.2.2 `copium wrap` Savings Summary (Enhanced)

After the agent session ends, print a combined savings summary:

```
  ┌─────────────────────────────────────────┐
  │  COPIUM SAVINGS SUMMARY                 │
  │  ─────────────────────────────────────  │
  │  RTK (CLI stdout):      14,200 tokens   │
  │  Proxy (all traffic):   38,900 tokens   │
  │  ─────────────────────────────────────  │
  │  Total saved:           53,100 tokens   │
  │  Estimated cost saved:  $0.42           │
  │  Cache hit rate:        67%             │
  └─────────────────────────────────────────┘
```

Implementation: Hook into the wrap cleanup path (already tracks `tokens_saved_rtk` via `_poll_rtk_delta()` in `copium/subscription/tracker.py:339`). Add proxy savings from the session tracker.

#### 3.2.3 `copium wrap` Agent Detection (New)

```bash
copium wrap  # no arguments
```

Auto-detect which agent the user has installed:
1. Check `which claude`, `which codex`, `which aider`, etc.
2. If exactly one found → wrap that agent
3. If multiple found → interactive prompt:
   ```
   Which agent would you like to wrap?
     1. Claude Code
     2. Codex
     3. Aider
     4. Cursor
   ```
4. If none found → install guidance

This is the `copium init` concept from `COPIUM_FEATURE_BRAINSTORM.md:45`.

#### 3.2.4 `copium wrap --verbose` Enhancement

The `-v` flag (already in every wrap subcommand) should print:

```
  Context tool: rtk v0.28.2 at ~/.copium/bin/rtk
  Proxy: started on port 8787 (token mode)
  Transforms: SmartCrusher, Kompress, CacheAligner, SessionDedup
  RTK instructions: injected into AGENTS.md
  MCP retrieve tool: registered
  Agent savings profile: agent-90
```

Currently `_setup_rtk` at `wrap.py:475` only prints "rtk found at" and "rtk hooks registered". Expand this.

---

## 4. Solving the "Strangeness Tax"

The strangeness tax is RTK's most criticized flaw. It's the phenomenon where compressed CLI output confuses LLMs because the output doesn't match their training distribution.

### 4.1 Root Cause Analysis

RTK's approach:
```
# RTK compresses git status to:
 M src/main.rs
 D tests/old_test.rs
?? new_feature.rs
```

But LLMs trained on full `git status` output expect:
```
# Full git status output:
On branch feature/new-thing
Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)

        modified:   src/main.rs
        deleted:    tests/old_test.rs

Untracked files:
  (use "git add <file>..." to include in what will be committed)

        new_feature.rs

no changes added to commit (use "git add" and/or "git commit -m")
```

The LLM's internal representation of "git status output" expects the verbose format. When it sees the compressed format, its reasoning about the repository state can degrade.

### 4.2 Copium's Multi-Layer Solution

#### Layer 1: Content-Type-Aware Compression (Already Exists)

Copium's `ContentRouter` (`crates/copium-core`) detects content type and dispatches to specialized compressors. This means:

- **Structured output** (JSON from APIs) → SmartCrusher (statistical compression preserving keys)
- **Code files** → Code compressor (preserves signatures, drops bodies)
- **Logs** → Log compressor (preserves errors, timestamps, drops verbose info)
- **Shell output** → Smart compression with LLM-friendly format

Each compressor preserves the **semantic structure** the LLM expects, not just raw token count.

#### Layer 2: Quality Gate (Proposed)

From `COPIUM_FEATURE_BRAINSTORM.md:35`. See also `plans/03-beat-claw-compactor.md` §3.1 for the Rust-based ROUGE-L quality gate implementation that integrates with the Claw-inspired 14-stage pipeline.

After each lossy compression step, re-measure with the tokenizer. If it doesn't actually save tokens (or drops quality below threshold), auto-revert the step.

```python
class QualityGate:
    """Post-compression quality check."""

    def check(self, original: str, compressed: str, content_type: str) -> bool:
        """Return True if compressed output is safe to use."""
        # 1. Token count must actually decrease
        if token_count(compressed) >= token_count(original):
            return False

        # 2. Critical markers must be preserved
        critical = self.extract_critical_markers(original, content_type)
        for marker in critical:
            if marker not in compressed:
                return False

        # 3. Semantic structure check (heuristic)
        if not self.structure_preserved(original, compressed, content_type):
            return False

        return True
```

Critical markers by content type:

| Content Type | Critical Markers |
|---|---|
| `git status` | Branch name, file paths, modification status indicators |
| `git diff` | `+`/`-` prefixes, hunk headers (`@@`) |
| Test output | Test counts, failure messages, error traces |
| Build output | Error lines, warning lines, exit codes |
| `grep`/`ripgrep` | File paths, line numbers, matched text |

#### Layer 3: CCR Retrieval Fallback (Already Exists)

When the LLM needs the full output after seeing compressed output, it calls `copium_retrieve` via MCP. The original is stored in the Compression Store and returned on demand.

This means: compression is lossy but **reversible**. The LLM can always ask for the full version.

#### Layer 4: Contextual Preservation (New)

For specific commands that LLMs are trained on, preserve more structure:

```python
# Command-specific preservation rules
PRESERVATION_RULES = {
    "git status": PreserveStructure(
        keep_headers=True,      # "On branch X", "Changes not staged"
        keep_file_paths=True,    # Always show full paths
        compress_descriptions=True,  # Drop "use git add..." hints
    ),
    "git diff": PreserveStructure(
        keep_hunk_headers=True,  # @@ -1,5 +1,7 @@
        keep_plus_minus=True,    # +/- line markers
        drop_context_lines=True, # Lines starting with space
    ),
    "pytest": PreserveStructure(
        keep_failures=True,      # Full failure output
        keep_summary=True,       # "X passed, Y failed"
        drop_passes=True,        # Individual passing test lines
    ),
}
```

### 4.3 Measuring the Strangeness Tax

Build a benchmark:

```bash
copium evals strangeness --agent claude --task "explain this git status"
```

Compare LLM task accuracy on:
1. Raw output (baseline)
2. RTK-compressed output
3. Copium-compressed output

Target: Copium-compressed output must achieve ≥98% of baseline accuracy.

---

## 5. Extending Beyond CLI Stdout

This is Copium's strongest differentiator. RTK only compresses what appears on stdout. Copium compresses everything.

### 5.1 Current Coverage Map

| Content Source | RTK | Copium Proxy | Copium Wrap+Proxy |
|---|---|---|---|
| CLI stdout (`git status`, `ls`, etc.) | Yes | No (not in API path) | **Both** (RTK + proxy) |
| CLI stderr | Partial (some filters) | No | **Both** |
| File reads (Read tool, `cat`) | No | Yes (tool_result blocks) | **Yes** |
| Search results (`grep`, `rg`) | Partial | Yes (tool_result blocks) | **Yes** |
| MCP tool outputs | No | Yes (tool_result blocks) | **Yes** |
| Conversation history | No | Yes (old turn compression) | **Yes** |
| RAG chunks | No | Yes (via proxy) | **Yes** |
| Agent reasoning/thinking | No | No (cache hot zone) | **No** (by design) |

### 5.2 New Compressors for Gap Content

#### 5.2.1 File Read Compressor

Agent reads are often entire files when only a few lines matter.

```
Agent: Read src/main.rs (847 lines)
LLM only needs: lines 45-67 (the function being discussed)

Current: sends all 847 lines (~12,000 tokens)
Compressed: sends relevant excerpt + file structure summary (~800 tokens)
```

Implementation: Use the existing `ContentRouter` to detect file reads in tool_result blocks. Apply:
1. **AST-based extraction** (Tree-sitter already in `crates/copium-core`) — extract only the relevant function/class
2. **Header-only compression** — send function signatures, drop bodies
3. **Diff-based compression** — if the file was previously sent, send only the changed regions

#### 5.2.2 Search Result Compressor

Search results (`grep`, `ripgrep`, LSP) often return hundreds of matches when only a few are relevant.

```
Agent: grep "handle_error" (returns 347 matches across 89 files)
LLM only needs: the 3-5 matches in the file being modified

Current: sends all 347 matches (~15,000 tokens)
Compressed: sends top matches by relevance + summary stats (~500 tokens)
```

Implementation: Already partially handled by SmartCrusher. Enhance with:
1. **BM25 relevance scoring** — rank matches by query relevance
2. **File proximity scoring** — prioritize matches in files the agent has already touched
3. **Deduplication** — collapse repeated patterns into "N matches across M files"

#### 5.2.3 Diff Compressor

Git diffs are huge but often contain noise.

```
Agent: git diff (2,400 lines, 50 files changed)
LLM only needs: the changed functions, not every whitespace change

Current: sends full diff (~35,000 tokens)
Compressed: sends semantic diff — changed function signatures + key changes (~3,000 tokens)
```

Implementation: Already partially handled. Enhance with:
1. **Whitespace collapse** — strip blank line changes, indentation-only changes
2. **Binary file exclusion** — detect and skip binary file diffs
3. **Rename detection** — collapse rename+modify into single entry

#### 5.2.4 Test Output Compressor

Test runs produce enormous output.

```
Agent: pytest tests/ (1,247 tests, 1,240 pass, 7 fail)
LLM only needs: the 7 failures + summary

Current: sends all output (~45,000 tokens)
Compressed: sends failures + summary (~2,000 tokens)
```

Implementation: Already partially handled by Log compressor. Enhance with:
1. **Pass/fail detection** — regex patterns for pytest, cargo test, jest, vitest
2. **Failure grouping** — collapse similar failures into one representative
3. **Stack trace truncation** — keep first/last frames, drop middle

### 5.3 The "Everything Pipeline"

```
                    ┌──────────────────────────────────┐
                    │          Copium Pipeline           │
                    │                                    │
  CLI stdout ──────│──▶ RTK (pre-filter, shell output)  │
  File reads ──────│──▶ SmartCrusher (JSON, structured) │
  Search results ──│──▶ SearchCompressor (relevance)    │
  Diffs ───────────│──▶ DiffCompressor (semantic)       │
  Test output ─────│──▶ LogCompressor (error-focused)    │
  API responses ───│──▶ SmartCrusher + CacheAligner      │
  Conversation ────│──▶ SessionDedup + TurnCompressor    │
                    │                                    │
                    │  Quality Gate ──▶ CCR Store ──▶ LLM │
                    └──────────────────────────────────┘
```

---

## 6. CLI-First Onboarding Strategy

### 6.1 The One-Liner Entry Point

RTK's onboarding is: `brew install rtk`. Copium must match this.

```bash
# Option 1: pip (Python users)
pip install "copium-ai[proxy]"

# Option 2: Docker-native (zero dependencies)
curl -fsSL https://copium.sh | bash

# Option 3: npm (Node.js users — for SDK)
npm install copium-ai
```

But the REAL entry point is:

```bash
copium wrap claude
```

That's it. One command. It does everything:
1. Downloads RTK binary (if not present)
2. Starts the Copium proxy
3. Configures Claude Code
4. Launches Claude Code

### 6.2 The "RTK Migration" Entry Point

For RTK users specifically:

```bash
# RTK user already has brew. They run:
pip install "copium-ai[proxy]"

# Then:
copium wrap claude --rtk-only   # Start with RTK-only, same as before

# After a week, they see savings in copium perf. Curiosity kicks in.
copium wrap claude              # Full proxy mode
```

### 6.3 Progressive Disclosure of Features

Don't overwhelm users on first run. The wrap command should:

**First run:**
```
  ✓ Copium proxy started (port 8787)
  ✓ RTK configured for Claude Code
  ✓ Claude Code launched

  Start saving: just use Claude Code normally.
  Check savings: copium perf
```

**After 1 hour of use (next `copium perf`):**
```
  Session stats: 23,400 tokens saved (41% compression)
  RTK savings:   8,200 tokens (CLI stdout)
  Proxy savings: 15,200 tokens (tool outputs, file reads)

  Tip: Run `copium wrap claude --verbose` to see all transforms.
```

**After 1 week (promoted features):**
```
  Weekly savings: 1.2M tokens ($9.60)
  Cache hit rate: 72% (saves 60% on repeated prefixes)
  CCR retrievals: 14 (LLM asked for full details 14 times)

  New: Enable memory for cross-session knowledge:
    copium wrap claude --memory
  New: Enable learning from failures:
    copium wrap claude --learn
```

### 6.4 The `copium doctor` Command (New)

A health check that validates everything is working:

```bash
$ copium doctor

  Checking Copium installation...
  ✓ copium-ai 1.2.3 installed
  ✓ rtk v0.28.2 installed at ~/.copium/bin/rtk
  ✓ Proxy starts on port 8787
  ✓ Claude Code detected

  Checking agent configuration...
  ✓ Claude Code hooks registered
  ✓ RTK instructions in AGENTS.md
  ✓ MCP retrieve tool configured

  Checking proxy health...
  ✓ Proxy responding at http://127.0.0.1:8787/health
  ✓ Transforms loaded: SmartCrusher, Kompress, CacheAligner
  ✓ Cache enabled

  All checks passed. Run `copium wrap claude` to start.
```

---

## 7. Marketing as "RTK on Steroids"

### 7.1 The Narrative

**RTK gave you the hook. Copium gives you the whole fish.**

RTK showed the world that LLM context compression works. 28K stars prove the demand. But RTK is a CLI filter — it only sees stdout. Copium is a context compression *layer* — it sees everything.

### 7.2 Key Messaging

#### Homepage Hero (steal RTK's thunder directly)

```
                          RTK                    Copium
  ─────────────────────────────────────────────────────────
  What it compresses:     CLI stdout             Everything
  Configuration:          Shell prefix           One command
  Reversibility:          None                   CCR (retrieval)
  Observability:          None                   Full metrics
  Agent support:          Shell hooks            Proxy + hooks + MCP
  File reads:             ✗                      ✓
  Search results:         Partial                ✓
  Conversation history:   ✗                      ✓
  Quality guarantees:     ✗                      Quality gate

  RTK: save 60-90% on CLI output.
  Copium: save 40-90% on ALL context. (Includes RTK for free.)
```

#### README Comparison Table (update existing at `README.md:321`)

```markdown
| | Scope | Deploy | Local LLMs | Reversible | Observability |
|---|---|---|:---:|:---:|:---:|
| **Copium** | All context — tools, RAG, logs, files, history | Proxy, library, MCP | Yes | Yes (CCR) | Full metrics |
| [RTK](https://github.com/rtk-ai/rtk) | CLI command outputs only | CLI wrapper | Yes | No | None |
```

#### Social Proof Angle

```
"RTK proved context compression works. Copium makes it production-ready."
```

### 7.3 GitHub Strategy

1. **Star-bait README** — RTK's README is terse. Copium's should be comprehensive but scannable. Lead with the savings table.
2. **"RTK" in keywords/description** — GitHub search for "RTK alternative" should surface Copium.
3. **Migration guide** — `docs/migrating-from-rtk.md` explaining exactly how to switch.
4. **Benchmark comparison** — `benchmarks/rtk-vs-copium/` with reproducible results.

### 7.4 Content Marketing

| Content | Angle |
|---|---|
| "RTK saved me 60%. Copium saved me 85%." | User story |
| "Why I moved from RTK to Copium" | Migration narrative |
| "RTK vs Copium: Which saves more tokens?" | Comparison post |
| "How Copium includes RTK and goes further" | Technical deep dive |

---

## 8. Integration with Claude Code, Cursor, Codex Hooks

### 8.1 Current Integration State

From `copium/cli/wrap.py` and `copium/rtk/installer.py:162`:

| Agent | Hook Mechanism | RTK Integration | Proxy Integration |
|---|---|---|---|
| **Claude Code** | `settings.json` hooks (PreToolUse) | `rtk init --global --auto-patch` | `ANTHROPIC_BASE_URL` env var |
| **Codex** | `config.toml` model provider | AGENTS.md injection | `model_provider = "copium"` + `openai_base_url` |
| **Aider** | `CONVENTIONS.md` injection | AGENTS.md injection | `OPENAI_API_BASE` env var |
| **Cursor** | `.cursorrules` injection | `.cursorrules` injection | Proxy URL config instructions |
| **Copilot** | `ANTHROPIC_BASE_URL` env var | RTK hooks | Proxy env var |
| **Cline** | `.clinerules` injection | `.clinerules` injection | VS Code settings |
| **Continue** | `config.json` system message injection | Config injection | Config injection |
| **Goose** | `.goosehints` injection | Hints injection | Env var |
| **OpenHands** | `OPENHANDS_INSTRUCTIONS` env var | Env var | Env var |

### 8.2 Claude Code Deep Integration

Claude Code is the primary target. The integration should be seamless.

#### 8.2.1 Hook Registration (Already Implemented)

`copium/rtk/installer.py:162` runs `rtk init --global --auto-patch` which adds a PreToolUse hook to `~/.claude/settings.json`. This hook intercepts Bash tool calls and runs them through RTK.

#### 8.2.2 Proxy Environment (Already Implemented)

`copium/cli/wrap.py:677` writes `ANTHROPIC_BASE_URL` into `.claude/settings.local.json` so all API calls route through the Copium proxy.

#### 8.2.3 MCP Retrieve Tool (Already Implemented)

`copium/cli/wrap.py:729` registers the Copium MCP server with Claude Code, providing `copium_retrieve` tool for CCR retrieval.

#### 8.2.4 Tool Deferral (Already Implemented)

`copium/cli/wrap.py:159` sets `ENABLE_TOOL_SEARCH=true` to keep Claude Code's tool deferral active behind the proxy, saving context on MCP/system tools.

#### 8.2.5 Enhancements Needed

1. **Hook for Read tool** — Currently RTK only hooks Bash. Add a PreToolUse hook for the Read tool that compresses large file reads:
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Read",
           "hooks": [{"type": "command", "command": "copium compress-read --max-lines 200"}]
         }
       ]
     }
   }
   ```

2. **Hook for Grep tool** — Compress search results before they enter context:
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Grep",
           "hooks": [{"type": "command", "command": "copium compress-search --max-results 50"}]
         }
       ]
     }
   }
   ```

3. **PostToolUse hook for Bash** — After RTK compresses stdout, optionally apply additional Copium transforms:
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Bash",
           "hooks": [{"type": "command", "command": "copium post-compress --type shell"}]
         }
       ]
     }
   }
   ```

### 8.3 Cursor Integration

Cursor uses `.cursorrules` for instruction injection and environment variables for proxy routing.

#### Current (from `copium/cli/wrap.py`)
- `.cursorrules` gets RTK instructions appended
- `copium wrap cursor` prints config instructions for the user to add manually

#### Enhancement
- Auto-inject proxy URL into Cursor's workspace settings
- Add `copium_compress` as a Cursor tool via MCP

### 8.4 Codex Integration

Codex uses `config.toml` for provider configuration.

#### Current (from `copium/cli/wrap.py:1297`)
- `model_provider = "copium"` is injected
- `openai_base_url` is set to proxy URL
- AGENTS.md gets RTK instructions
- MCP memory server is registered

#### Enhancement
- Add Codex-specific preservation rules for Codex's output format
- Support Codex's WebSocket transport for streaming compression

### 8.5 Universal Hook Pattern

Create a `copium hook` command that generates hook configurations for any agent:

```bash
copium hook claude     # Generates Claude settings.json hooks
copium hook codex      # Generates Codex AGENTS.md + config.toml
copium hook cursor     # Generates .cursorrules + settings
copium hook generic    # Generates generic shell hooks (works with any agent)
```

The `generic` output is a shell script that any agent can use:

```bash
#!/bin/bash
# copium-hooks.sh — source this in your agent's environment
copium_compress_read() { copium compress-read "$@"; }
copium_compress_search() { copium compress-search "$@"; }
copium_compress_diff() { copium compress-diff "$@"; }
```

---

## 9. Implementation Roadmap

### Phase 1: Drop-in RTK Replacement (Week 1-2) ✅ COMPLETE

| Task | Files | LOC Est. | Status |
|---|---|---|---|
| Add `--rtk-only` flag to all wrap commands | `copium/cli/wrap.py` | +150 | ✅ Done |
| Enhance savings summary output | `copium/cli/wrap.py` | +200 | ✅ Done |
| Add agent auto-detection | `copium/cli/wrap.py` | +300 | ✅ Done |
| Add `copium doctor` command | `copium/cli/doctor.py` | +400 | ✅ Done (enhanced) |
| Strangeness tax quality gate | `copium/transforms/quality_gate.py` | +500 | ✅ Done (Gate 4) |
| Content preservation rules | `copium/transforms/preservation.py` | +300 | ✅ Done |
| Read/Grep hook commands | `copium/cli/hooks_compress.py` | +200 | ✅ Done |
| Enhanced verbose output | `copium/cli/wrap.py` | +150 | ✅ Done |
| RTK migration guide | `docs/migrating-from-rtk.md` | docs | ✅ Done |
| Update rtk-architecture.md | `docs/rtk-architecture.md` | docs | ✅ Done |

### Phase 2: Beyond Stdout (Week 3-4)

| Task | Files | LOC Est. |
|---|---|---|
| File read compressor | `crates/copium-core/src/transforms/file_read.rs` | +800 |
| Search result compressor | `crates/copium-core/src/transforms/search.rs` | +600 |
| Diff compressor enhancement | `crates/copium-core/src/transforms/diff.rs` | +400 |
| Test output compressor | `crates/copium-core/src/transforms/test_output.rs` | +500 |
| Wire Read/Grep hooks into `copium wrap claude` | `copium/cli/wrap.py` | +200 |

### Phase 3: Agent Deep Integration (Week 5-6)

| Claude Code Read/Grep hooks | `copium/cli/wrap.py`, `copium/hooks/` | +400 | TODO |
| Universal hook generator | `copium/cli/hook.py` (new) | +300 | TODO |
| Cursor auto-configuration | `copium/providers/cursor.py` (new) | +200 | TODO |
| Enhanced verbose output | `copium/cli/wrap.py` | +150 | TODO |

### Phase 4: Marketing + Migration (Week 7-8)

| Task | Files | LOC Est. | Status |
|---|---|---|---|
| RTK migration guide | `docs/migrating-from-rtk.md` (new) | docs | TODO |
| Benchmark comparison | `benchmarks/rtk-vs-copium/` (new) | tooling | TODO |
| README update | `README.md` | docs | TODO |
| Strangeness tax benchmark | `tests/test_evals/strangeness.py` (new) | +500 | TODO |

---

## 10. Success Metrics

| Metric | Target | Measurement |
|---|---|---|
| **RTK user migration rate** | 30% of new users come from RTK | GitHub referrer tracking, survey |
| **Strangeness tax reduction** | <2% accuracy drop on compressed output | `copium evals strangeness` benchmark |
| **CLI stdout compression parity** | Within 5% of RTK's compression ratio | Side-by-side benchmark |
| **Beyond-stdout compression** | 40-90% on file reads, search results, diffs | Per-transform metrics |
| **One-command onboarding** | `copium wrap claude` succeeds on first try for 95% of users | Error rate tracking |
| **GitHub stars** | 5K within 6 months of RTK-on-steroids launch | GitHub API |

---

## 11. Risk Mitigation

| Risk | Mitigation |
|---|---|
| RTK users resist change | `--rtk-only` mode provides identical UX; proxy features are opt-in |
| Quality gate too aggressive | Configurable thresholds; lossless-only preset for cautious users |
| Hook compatibility breaks | Version-pin RTK binary; test against RTK's latest release |
| Proxy overhead deters users | Show overhead is <52ms (already measured); `--no-proxy` bypass |
| Feature bloat confuses users | Progressive disclosure; `copium doctor` validates setup; clean defaults |
| RTK proxy-side integration requested | Rejected per decision in `docs/rtk-architecture.md` — cache hot zone risk + parallel impl with `log_compressor.rs`; RTK stays wrap-CLI only |

---

## 12. Open Questions

1. **Should we fork RTK or vendor it?** Currently vendored (`RTK_VERSION = "v0.28.2"` at `copium/rtk/__init__.py:15`). Forking allows customization but increases maintenance. Recommendation: keep vendoring, add Copium-specific wrappers.

2. **Should `copium wrap --rtk-only` be a separate binary?** Some users might want a single binary like RTK. The `copium` CLI is already a single entry point, but the Python dependency is heavier than RTK's Rust binary. Consider a `copium-lite` binary in the future.

3. **How aggressive should the strangeness tax quality gate be?** Too aggressive and compression ratios drop. Too lax and LLMs get confused. Need benchmark data before deciding defaults.

4. **Should we contribute back to RTK?** PRs that improve RTK's `--format json` output (for `copium perf` integration) benefit both projects. Good for community goodwill.

5. **Timeline alignment with Phase G (ROADMAP/09)?** Phase G extends wrap breadth to cline/continue/goose/openhands and adds observability. This plan builds on top of that foundation. Phase G should land first.

6. **Phase B (ROADMAP/04) prerequisite?** Section 5 ("Beyond Stdout") assumes the live-zone compression engine from Phase B is in place. The new compressors (file_read, search, test_output) dispatch through `ContentRouter` which is part of the live-zone architecture. Phase B should complete before Phase 2 of this plan begins.
