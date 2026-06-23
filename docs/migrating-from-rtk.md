# Migrating from RTK to Copium

**Status:** Current  
**Last updated:** 2026-06-23  
**Target audience:** RTK users who want more savings, observability, and reversibility.

---

## TL;DR

```bash
# Step 1: Install Copium (keeps RTK functionality)
pip install "copium-ai[proxy]"

# Step 2: Drop-in replacement — same CLI savings as RTK, nothing else changes
copium wrap claude --rtk-only

# Step 3: Unlock full proxy savings whenever you're ready
copium wrap claude
```

That's it. Copium **includes RTK** and adds everything RTK can't do.

---

## Why migrate?

RTK is brilliant at one thing: compressing what appears on stdout. Copium
includes RTK for free and extends compression to every part of the context
window RTK can't reach.

| Capability | RTK | Copium |
|---|:---:|:---:|
| CLI stdout (`git status`, `ls`) | ✓ | ✓ (via RTK) |
| CLI stderr / errors | Partial | ✓ |
| File reads (`cat`, Read tool) | ✗ | ✓ |
| Search results (`grep`, `rg`) | Partial | ✓ |
| MCP tool outputs | ✗ | ✓ |
| Conversation history dedup | ✗ | ✓ |
| RAG chunks | ✗ | ✓ |
| CCR retrieval (reversible) | ✗ | ✓ |
| Observability (`copium perf`) | ✗ | ✓ |
| Quality gate (no strangeness tax) | ✗ | ✓ |
| Configuration needed | None | `pip install copium-ai` |

**Typical combined savings: 40–90% on all context, vs 60–90% on CLI stdout only.**

---

## Stage-by-stage migration

### Stage 1: Drop-in replacement (Week 1)

Use `--rtk-only` to get identical behaviour to plain `rtk`, with zero proxy
startup overhead. This is perfect for RTK users who want to try Copium
without committing to the proxy.

```bash
# Before (RTK + Claude Code)
# You were running: claude  (with RTK hooks already registered)

# After (Copium --rtk-only, same outcome)
copium wrap claude --rtk-only
```

What changes: nothing visible. RTK is configured exactly the same way.
What you gain: `copium perf` will start tracking your RTK savings so you can
see how much CLI stdout compression is contributing.

### Stage 2: Discover the upgrade

After a session or two, check your savings:

```bash
copium perf
```

You'll see RTK savings for CLI stdout. Now see what you're missing by adding
the proxy:

```bash
copium wrap claude   # Full mode — proxy + RTK
```

The savings breakdown appears at session end:

```
  ┌─────────────────────────────────────────────┐
  │           COPIUM SAVINGS SUMMARY             │
  │─────────────────────────────────────────────│
  │  RTK (CLI stdout):       14,200 tokens       │
  │  Proxy (all traffic):    38,900 tokens       │
  │─────────────────────────────────────────────│
  │  Total saved:            53,100 tokens       │
  │  Estimated cost saved:   $0.42               │
  │  Cache hit rate:         67%                 │
  └─────────────────────────────────────────────┘
```

### Stage 3: Full Copium activation

```bash
# Proxy intercepts all traffic. RTK remains active for CLI stdout.
copium wrap claude
```

From here, the proxy handles:
- **File reads** (Read tool) — AST-aware extraction of relevant functions
- **Search results** — BM25 relevance ranking, deduplication
- **Git diffs** — semantic compression, whitespace collapse
- **Test output** — failure-focused, drop passing test lines
- **Conversation history** — cross-turn deduplication
- **API responses** — JSON/structured content compression

RTK still handles CLI stdout (the shell `Bash` tool) — it runs first, at
the exec boundary, and the proxy handles everything else.

### Stage 4: Optional — full Copium features

```bash
copium wrap claude --memory   # Cross-session memory
copium wrap claude --learn    # Traffic pattern learning
copium wrap claude --code-graph  # Code intelligence
```

---

## What stays the same

- **RTK binary**: still downloaded and used. No behaviour change.
- **RTK instructions in AGENTS.md**: still injected. The agent still prefixes
  commands with `rtk`.
- **Shell output format**: LLMs still see RTK-compressed stdout. Copium adds
  compression on top, not instead.

---

## What changes

- **Proxy starts on port 8787** (unless `--no-proxy` or `--rtk-only` is used).
  Latency overhead is typically <52ms per request on localhost.
- **`ANTHROPIC_BASE_URL` is redirected** to `http://127.0.0.1:8787` so all
  API calls route through Copium. This is written to `.claude/settings.local.json`
  for the current project only.
- **MCP retrieve tool is registered**: Claude can call `copium_retrieve` to
  fetch the original version of any compressed content (CCR — Compress-Cache-Retrieve).

---

## Verifying the migration

Run `copium doctor` to validate everything is working:

```bash
$ copium doctor

  Copium Doctor
  ==================================================

  ✓ Python 3.12.3
  ✓ Platform: Darwin (arm64)
  ✓ copium-ai 1.2.3 installed
  ✓ Rust core: loaded

  Checking RTK (CLI context tool)...
  ✓ rtk v0.28.2 installed at ~/.copium/bin/rtk

  Checking agent configuration...
  ✓ Claude Code detected at /usr/local/bin/claude
  ✓ RTK instructions in Claude settings.json hooks

  Checking proxy health (port 8787)...
  ✓ Proxy responding at http://127.0.0.1:8787/health (v1.2.3)

  ✓ Copium MCP retrieve tool registered in Claude

  Checking data stores...
  ✓ CCR store: initialized

  ✓ All checks passed!
  Run `copium wrap claude` to start a session.
```

---

## Rollback

If you want to go back to plain RTK:

```bash
# Remove Copium's Claude hooks and proxy config
copium unwrap claude

# Restore RTK hooks (if you want RTK without Copium)
rtk init --global --auto-patch
```

---

## FAQ

**Q: Will RTK's savings be double-counted?**  
A: No. `copium perf` separates RTK savings (CLI stdout) from proxy savings
(all other traffic). They're additive, not overlapping.

**Q: Does the proxy slow down my agent?**  
A: Measured overhead is <52ms per request on localhost. For typical agent
sessions this is imperceptible against LLM latency (1–30 seconds per turn).

**Q: Can I use Copium with Codex, Aider, or Cursor instead of Claude Code?**  
A: Yes. Use `copium wrap codex`, `copium wrap aider`, or `copium wrap cursor`.
All wrap subcommands support RTK integration.

**Q: What if I only want --rtk-only for some sessions and full proxy for others?**  
A: Each `copium wrap` invocation is independent. Use `--rtk-only` when you want
lightweight sessions and omit it for full compression.

**Q: Where are the proxy logs?**  
A: `~/.copium/logs/proxy.log`. The path is also printed on proxy startup.

---

## References

- `plans/04-beat-rtk.md` — Full competitive analysis and implementation plan
- `docs/rtk-architecture.md` — Why RTK is wrap-CLI only (not proxy-side)
- [RTK GitHub](https://github.com/rtk-ai/rtk) — The RTK project we integrate
- `copium doctor` — Health check command
- `copium perf` — Savings dashboard
