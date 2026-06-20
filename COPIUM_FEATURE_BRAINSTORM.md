# Copium Feature Brainstorm

> Date: 2026-06-20

---

## Current Gaps Identified

- No differential responses (diffs for repeated tool calls)
- No TUI dashboard
- No schema optimizer
- No per-request transform control headers
- No output compression
- No quality gate
- No VCS-aware prioritization
- No recipe system
- No A/B testing
- No TOON encoding
- No model routing

---

## Feature Brainstorm — Prioritized

### Tier 1: High Impact, Feasible (Do First)

#### 1. Output Compression
- Compress what the model *writes back* (not just input). Drop ceremony, restate code, skip deep thinking on routine steps.
- Output compression can hit -74% savings.
- **This is a huge untapped area — most tools focus only on input.**

#### 2. Quality Gate
- After each lossy compression step, re-measure with the tokenizer. If it doesn't actually save tokens (or drops quality below threshold), auto-revert the step.
- Makes compression safe-by-default. Users never get a higher bill.

#### 3. Differential Responses
- For repeated tool calls (e.g., `git status`, polling), send a unified diff instead of full output.
- Up to 95% savings on polling patterns.
- Add a `copium_diff_respond` or modify CCR to track last-sent version per tool.

#### 4. Per-Request Transform Control Headers
- `X-Copium-Disable: toon,code_compressor` — disable specific transforms per request without affecting other clients.
- Essential for debugging, A/B testing, and gradual rollout.

#### 5. `copium init` Auto-Setup UX
- One command: `copium init claude` / `copium init cursor` — auto-configures the proxy URL, installs hooks, detects installed agents.
- You already have `copium wrap`, but a guided `init` with agent detection would be smoother.

#### 6. TOON Encoding
- Token-Oriented Object Notation — encodes JSON arrays into a compact table format (15-40% savings).
- SmartCrusher handles arrays but TOON is a complementary format for uniform structures.

---

### Tier 2: Differentiation (Do Next)

#### 7. Schema Compression
- Specifically target OpenAI Function Calling tool definitions. Tool schemas get resent identically every turn — compress them once, reuse across turns.
- ~57% reduction on schemas is achievable.

#### 8. Git-Aware File Prioritization
- Rank files by commit frequency, recency, author match, branch relevance, dependency centrality.
- Use VCS history as an importance signal for codebase ingestion.
- Multi-signal scoring: `Priority = 0.30*commit_freq + 0.20*recency + 0.10*author_match + 0.10*branch_relevance + 0.15*file_type + 0.15*dependency_centrality`.

#### 9. TUI Dashboard
- Real-time terminal dashboard (ratatui) showing: tokens saved, dollars saved, per-transform breakdown, cache hit rate, live request stream.
- The web dashboard is good but a TUI fits the CLI-first workflow.

#### 10. Model Routing
- Route requests to cheaper models automatically: simple tasks -> `gpt-4o-mini`, complex -> `gpt-4o`.
- 30-60% savings achievable. Could be done via a complexity classifier (even a simple heuristic).

#### 11. Auto-Batching
- Route async-tolerant calls to provider Batch APIs (OpenAI Batch, Anthropic Message Batches — both 50% off).
- Add a `copium_batch` flag for non-urgent requests.

#### 12. Chain-of-Draft Output Control
- Inject a terse-output instruction that gets the model to produce shorter answers without quality loss.
- A cheap way to cut output costs.

---

### Tier 3: Architecture/UX Improvements

#### 13. Compression Recipe System
- YAML-configurable compression recipes.
- Users can share/extend recipes: `copium recipe apply agent-heavy` / `copium recipe apply rag-pipeline`.

#### 14. A/B Benchmarking Framework
- Run two compression configs side-by-side, measure cost AND quality on the same prompts.
- Essential for proving value.

#### 15. Visual Analytics
- Pie charts showing token distribution by category, compression savings by content type.
- Could be a `copium report` subcommand.

#### 16. Lossless-Only Mode (`safe` preset)
- A compression mode that only applies lossless transforms. Risk-averse users can start here.

#### 17. Provider-Cache Composition
- Explicitly compose with provider caching: mark stable prefixes with `cache_control`, compress the variable suffix. Both savings stack.

#### 18. MCP Server Improvements
- Existing MCP is good. Enhance with: `copium_compress`, `copium_retrieve`, `copium_stats` tools exposed over stdio.
- Make it a first-class citizen for Claude Code / Codex integration.

#### 19. Multi-Language Embeddable Library
- Rust core already exists. Expose it as a library (UniFFI bindings to Python/Ruby/Swift/Kotlin/WASM), not just a proxy.

#### 20. Budget Enforcement + Spend Guard
- Pre-send circuit breaker: block runaway requests before they hit the provider.
- Directive-based: `[TIP: allow=once max=$X]`.

---

## Architecture Changes Worth Considering

| Current | Potential Change | Why |
|---|---|---|
| Proxy-only model | Add library-first mode | Some users want embedded, not proxied |
| Single compression pass | Two-pass (lossless first, then lossy with quality gate) | Safer, more predictable |
| No output compression | Add output transform stage | Huge untapped savings |
| No model routing | Add complexity classifier + router | Route simple->cheap, complex->expensive |
| No diff tracking | Add per-tool version tracking | Enable differential responses |

---

## Top 5 "Quick Wins" (highest effort-to-impact ratio)

1. **Per-request headers** (`X-Copium-Disable`) — ~1 day, huge debugging value
2. **`copium init` agent detection** — ~2 days, best onboarding UX
3. **Output compression** — ~1 week, 30-74% additional savings
4. **Quality gate** — ~1 week, makes compression safe-by-default
5. **TOON encoding** — ~3 days, 15-40% extra on structured data
