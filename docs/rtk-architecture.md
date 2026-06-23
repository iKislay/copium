# RTK architecture — why wrap-CLI only

**Status:** decided. Locked at Phase G PR-G3 (2026-05).
**Owner:** Copium roadmap.

## TL;DR

**RTK is a wrap-CLI hook, not a proxy-side compressor.** The Copium
proxy does NOT invoke RTK on tool-result content. Future contributors
who consider moving RTK into the proxy hot path: read this doc first.

## Background

RTK (Realtime Token Kompress) rewrites shell **commands** at exec
time so that a `git diff` or `grep` invocation emits a more
compressed output before the agent ever ingests it. RTK runs in the
wrap-CLI tail — `copium wrap claude`, `copium wrap codex`, etc.
— where it installs a `~/.rtk/bin/rtk` shim ahead of the agent CLI
and intercepts shelled-out subprocesses.

It surfaces value in two places:
1. **Tokens saved per invocation** — measured by `rtk gain --format json`.
2. **Tokens saved per session** — aggregated at wrap-session end.

Both signals feed `wrap_rtk_invocations_total` and
`wrap_rtk_tokens_saved_per_session` (registered by the Rust proxy's
observability surface so a single `/metrics` scrape exposes the full
picture).

## Proxy-side RTK was considered and rejected

At Phase G scoping, three reviewers floated the idea of invoking
RTK on the **proxy** side: when a `tool_result` block flows
upstream, dispatch it through RTK to shrink the content before it
hits the model.

**Decision: rejected.** Three load-bearing reasons.

### 1. Cache hot zone risk

The proxy's Phase B cache-safety contract pins `tool_result`
content as part of the cache hot zone. Compression there bursts
the prompt cache because the rewritten bytes diverge from the
canonical wire bytes the upstream cached. Phase B PR-B2 → PR-B7
spent ~3000 LOC carving the live-zone-only surface specifically
to prevent this class of cache-invalidation. Inserting RTK
proxy-side would re-introduce it.

### 2. Parallel implementation with `log_compressor.rs`

The Rust proxy already has a `crates/copium-core/src/transforms/log_compressor.rs`
that compresses **tool output text** in the live zone. It uses the
same heuristics RTK uses (whitespace de-dup, line de-dup,
file-listing collapse) but invoked at the proxy's per-block
dispatcher rather than at the shell exec boundary. Adding RTK
proxy-side would mean two implementations of the same compression
in the same hot path; "no silent fallbacks, no parallel impls" is
explicit project policy.

### 3. Command-rewrite vs output-rewrite — different value propositions

RTK rewrites **commands** before they execute. The
`git log --oneline` you typed becomes `git log --oneline -n 50`
because RTK has learned that the first 50 commits are usually
enough context. That's a fundamentally different mechanism from
compressing the **output** of an unmodified command. A proxy-side
invocation would skip the command-rewrite half — the half that
generates the largest savings on heavy shell workloads — and only
catch the output side, which is already covered by
`log_compressor` and `code_compressor`.

## What the proxy does provide

Per Phase G PR-G3, the proxy exposes RTK-derived metrics via its
registry:

- `wrap_rtk_invocations_total{tool}` — driven by the wrap-CLI
  polling `rtk gain --format json` and incrementing the registered
  counter by the delta since last poll.
- `wrap_rtk_tokens_saved_per_session` — emitted at wrap-session
  close.

This keeps the operator dashboard single-pane-of-glass without
re-implementing RTK inside the proxy.

## What the wrap CLI does

Every `copium wrap <agent>` subcommand:

1. Ensures the RTK binary is installed via `_ensure_rtk_binary()`.
2. Injects the `<!-- copium:rtk-instructions -->` block into the
   agent's instruction file (e.g. `AGENTS.md`, `.cursorrules`).
3. Spawns the proxy and the agent CLI side-by-side.
4. Polls `rtk gain --format json` on a 5-second memoization window
   and feeds the delta into the proxy's metric registry.

See `copium/cli/wrap/` for the per-agent shims.

## Re-litigation policy

A change to this architecture should:

1. Quote the live-zone-only contract from
   `ROADMAP/04-phase-B-live-zone.md` and explain why the
   cache-burst risk is acceptable.
2. Show measurements (not estimates) that proxy-side RTK adds value
   beyond `log_compressor.rs` on real production traffic.
3. Have an exit ramp: a CLI flag to disable proxy-side RTK without
   reverting the wrap-CLI integration.

Without all three, treat the proposal as a regression and link this
doc.

## References

- `ROADMAP/09-phase-G-rtk-observability.md` — Phase G plan.
- `ROADMAP/04-phase-B-live-zone.md` — cache hot-zone contract.
- `copium/cli/wrap/` — wrap-CLI implementation.
- `crates/copium-core/src/transforms/log_compressor.rs` — the
  proxy-side log compressor RTK would parallel.
- 2026-05-01 user direction message archived in
  `project_compression_roadmap_2026_05` memory note.

---

## Beat-RTK strategy (2026-06)

The above sections document *why* RTK is wrap-CLI only. This section
documents *how* Copium absorbs RTK's audience. See `plans/04-beat-rtk.md`
for the full competitive analysis, implementation roadmap, and success
metrics.

### Positioning

```
RTK:    rtk git status       → compresses CLI stdout    → 60-90% on stdout
Copium: copium wrap claude   → compresses EVERYTHING    → 40-90% on all context
                               (includes RTK for stdout)
```

**Pitch:** "Copium includes RTK for free, plus compresses everything RTK can't reach."

### RTK-only mode (`--rtk-only`)

RTK users can start with an exact drop-in replacement:

```bash
copium wrap claude --rtk-only
```

This:
- Downloads RTK binary and registers hooks
- Launches the agent (Claude Code, Codex, Aider, etc.)
- Does **not** start the proxy
- Shows RTK savings at session end via `_print_wrap_savings_summary`

When they're ready to unlock proxy savings, they drop `--rtk-only`.

### Agent auto-detection

```bash
copium wrap   # no args
```

Auto-detects installed agents in PATH (claude, codex, aider, goose,
openhands). Single agent found → auto-launches. Multiple found → numbered
menu. None found → install guidance.

### Strangeness tax mitigation (Gate 4)

RTK's most criticised flaw: compressed CLI output confuses LLMs because
the compressed format doesn't match training data. Copium's `QualityGate`
now implements **Gate 4: content-type-aware critical marker preservation**.

When a compressor drops critical structural markers:
- `git_status`: branch name, file paths, status codes
- `git_diff`: hunk headers (`@@`), `+++`/`---` file names
- `test_output`: pass/fail summary, `FAILED` test names
- `build_output`: error/warning lines with file:line references
- `grep`/`ripgrep`: file:line:content match lines

…the gate reverts that compression step rather than sending semantically
degraded output to the LLM. This targets ≥98% accuracy on compressed vs
baseline output (plan §4.3 benchmark target).

See `copium/transforms/quality_gate.py` for the implementation.

### Migration path

See `docs/migrating-from-rtk.md` for the full step-by-step guide RTK users
should follow.

### Enhanced `copium doctor`

`copium doctor` now validates the full RTK + Copium installation:
- RTK binary version
- Agents in PATH
- Claude RTK hook registration
- Proxy health at `/health`
- MCP retrieve tool registration
- CCR store, telemetry, API keys
