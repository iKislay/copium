# Phase H — Python Proxy Retirement

**Goal:** With Rust at full parity (Phases A–G), delete the Python proxy server, handlers, transforms, and supporting modules. Keep Python only where it's the right tool: CLI wrappers, RTK installer, evals, learn, memory writers, tokenizers (parity backstop).

**Calendar:** 2 weeks.

**Shape:** 3 PRs. H1 retires the request-path Python; H2 retires Bedrock/Vertex backend; H3 cleans up.

**Pre-requisites:**
- Phase A–G complete.
- Real-traffic shadow test (Phase I) shows Rust ≥99.9% byte-equality vs Python on representative traffic.
- Cache-hit-rate parity with direct upstream confirmed (Phase G observability).
- All Bedrock/Vertex paths covered by native Rust handlers (Phase D).

---

## PR-H1 — Retire Python proxy request path

**Branch:** `realign-H1-retire-python-proxy-request-path`
**Worktree:** `~/claude-projects/copium-worktrees/realign-H1-retire-python-proxy-request-path`
**Risk:** **HIGH** (production-facing change; canary deploy mandatory)
**LOC:** **-15,000 / +500**

### Scope
Delete the Python FastAPI server, all handlers, the responses converter (already gone in Phase C PR-C5), memory subsystem (replaced by live-zone tail injection from Phase A PR-A2 and Phase B PR-B6), semantic cache, batch handler, etc. The Rust proxy becomes the canonical request-path implementation. Operators run only `copium-proxy` (Rust binary).

### Files

**Delete:**
- `copium/proxy/server.py` (2864 LOC)
- `copium/proxy/handlers/anthropic.py` (2423 LOC)
- `copium/proxy/handlers/openai.py` (2742 LOC)
- `copium/proxy/handlers/streaming.py` (1131 LOC)
- `copium/proxy/handlers/gemini.py` (839 LOC)
- `copium/proxy/handlers/batch.py` (1010 LOC)
- `copium/proxy/responses_converter.py` — already deleted in PR-C5; verify gone.
- `copium/proxy/memory_handler.py` (1756 LOC)
- `copium/proxy/memory_tool_adapter.py` (1273 LOC)
- `copium/proxy/semantic_cache.py` (142 LOC)
- `copium/proxy/savings_tracker.py` (934 LOC) — re-implemented in Rust as part of `observability/`.
- `copium/proxy/loopback_guard.py` (92 LOC) — Rust equivalent in `crates/copium-proxy/src/handlers/debug.rs`.
- `copium/proxy/ws_session_registry.py` (226 LOC) — Rust equivalent.
- `copium/proxy/interceptors/` — all of this directory.
- `copium/proxy/cost.py`, `helpers.py`, `rate_limiter.py`, `request_logger.py` — re-implemented in Rust as part of compression dispatch / observability.
- `copium/proxy/prometheus_metrics.py` — re-implemented in Rust as `observability/prometheus.rs`.
- `copium/proxy/extensions.py`, `models.py`, `modes.py`, `stage_timer.py`, `warmup.py`, `responses_converter.py`, `debug_introspection.py`.
- `copium/transforms/cache_aligner.py` — already gutted in Phase A PR-A2; delete the remaining stub.

**Move:**
- `copium/proxy/loopback_guard.py` test logic → `crates/copium-proxy/tests/integration_loopback_guard.rs`.

**Modify:**
- `copium/cli/proxy.py` — `copium proxy start` now spawns the Rust binary (`./target/release/copium-proxy`) instead of `uvicorn copium.proxy.server:app`.
- `copium/cli/wrap/*.py` — same: env-var setup remains, but `proxy_url` points at the Rust binary's listen address.
- `pyproject.toml` — remove `fastapi`, `uvicorn`, `pydantic`, etc. from runtime deps; keep them in dev/test deps for parity harness only.
- `Dockerfile` — drop the Python proxy server stage; the Rust binary is the only proxy.
- `docker-compose.yml` — same.
- `RUST_DEV.md` — promote the Rust proxy from "Phase 1 transparent reverse proxy" to "the proxy."
- All operator runbooks in `guides/` and `docs/` — update to reference Rust binary.

**Tests deleted:**
- `tests/test_proxy_*.py` — most of these (which test the Python proxy directly). Keep tests that exercise CLI wrappers, RTK, evals, learn, memory writers, tokenizers.
- Roughly 150 test files; keep ~40 that don't depend on the Python proxy.

**Tests added:**
- `e2e/proxy_full/test_e2e_canary.py` — deploys the Rust binary in a container; runs a full conversation suite; asserts cache hit rate, compression value, no 5xx errors. Run pre-merge in CI.

### Acceptance criteria

- `pytest -x` green (after deletions).
- `cargo test --workspace` green.
- `make ci-precheck` green.
- E2E canary in CI passes.
- Manual test: `copium proxy start` boots the Rust binary; `curl -s http://127.0.0.1:8787/healthz` returns OK.
- Operator deploys the new image to staging; cache hit rate ≥ Python baseline; no 5xx regressions in 24h.

### Blocked by

PR-A1 through PR-G3.

### Blocks

PR-H2.

### Rollback

`git revert` of just this PR restores the Python proxy. **Critical**: keep the previous container image around for at least 30 days so operators can pin to the pre-H1 image. Document the rollback path in `docs/operations/rollback.md`.

### Notes

- This is the largest single PR in the roadmap. Coordinate with operations team.
- Do NOT delete in one giant commit; split into a series of smaller commits within the PR (one per module deletion) for git-blame friendliness.

---

## PR-H2 — Retire LiteLLM Bedrock/Vertex backend

**Branch:** `realign-H2-retire-litellm-backends`
**Worktree:** `~/claude-projects/copium-worktrees/realign-H2-retire-litellm-backends`
**Risk:** **MEDIUM**
**LOC:** **-3,000 / +100**

### Scope
After Phase D PR-D1..D4 added native Bedrock/Vertex Rust paths, the LiteLLM Python converter is no longer on any request path. Delete it.

### Files

**Delete:**
- `copium/backends/litellm.py` (~1500 LOC, the lossy converter)
- `copium/backends/__init__.py` if the only contents was the LiteLLM backend.

**Modify:**
- `pyproject.toml` — remove `litellm` from dependencies. (Saves ~50 MB of installed-deps size.)
- `copium/providers/registry.py` — delete `litellm-bedrock`, `litellm-vertex` provider entries.
- `copium/cli/wrap/*` — verify no wrap CLIs route to LiteLLM (they shouldn't; they go through the proxy).

**Tests deleted:**
- `tests/test_backends_litellm*.py`

### Acceptance criteria

- `pytest -x` green.
- A real Bedrock request through the Rust proxy succeeds (already validated in Phase D PR-D1 manual test).

### Blocked by

PR-H1, PR-D1, PR-D2, PR-D4.

### Blocks

PR-H3.

### Rollback

`git revert`. Restores LiteLLM. The Rust native paths from Phase D stay in place; both run side-by-side temporarily.

---

## PR-H3 — Final cleanup: orphaned modules, deps, docs

**Branch:** `realign-H3-final-cleanup`
**Worktree:** `~/claude-projects/copium-worktrees/realign-H3-final-cleanup`
**Risk:** **LOW**
**LOC:** -2,000 / +500

### Scope
Sweep up everything orphaned by H1+H2: unused imports, dead test fixtures, stale docs, legacy CLI commands. Update all README / wiki / docs to reflect the Rust-only proxy.

### Files

**Modify:**
- `README.md` — operator-facing docs reflect the Rust binary.
- `guides/` — refresh.
- `docs/` — refresh.
- `RUST_DEV.md` — final form (renamed to `DEV.md` since there's no longer a Python/Rust split).
- `copium/__init__.py` — drop unused module imports.
- `pyproject.toml` — final dependency cleanup.
- `Cargo.toml` — final workspace cleanup.

**Delete:**
- `tests/parity/fixtures/` — most of these are used by Python parity comparators that no longer have a Python side. Keep only the fixtures that still gate Rust-vs-Rust parity (which is: none, after Phase H — though future ML compressor variants may want them back).
- `crates/copium-parity/` — the parity harness itself becomes irrelevant after Python side is gone. **Decision needed** (see `12-decisions-needed.md` Q3): keep parity-run as a "prior-version-vs-current-version" harness, or delete?

**Add:**
- `CHANGELOG.md` entry: "**Breaking**: Python proxy retired. Operators must use the Rust binary `copium-proxy`. See migration guide at `docs/operations/python-to-rust-migration.md`."
- `docs/operations/python-to-rust-migration.md` — operator migration guide.

### Acceptance criteria

- `git grep -i "uvicorn\|fastapi" copium/` returns nothing in non-test code.
- `pyproject.toml` runtime deps are minimal.
- All docs build.

### Blocked by

PR-H1, PR-H2.

### Blocks

None.

### Rollback

`git revert`. Restores cleanup; previous PRs stay.

---

## What survives in Python after Phase H

| Module | Role | Reason |
|---|---|---|
| `copium/cli/wrap/*.py` | Agent launchers | Off-path; orchestrates filesystem + subprocess. Python is the right tool. |
| `copium/cli/{evals,init,install,learn,memory,perf,proxy,tools}.py` | CLI admin commands | Click-based; off-path. |
| `copium/rtk/installer.py` | RTK binary downloader | Off-path; filesystem operations. |
| `copium/providers/codex/install.py`, `claude/install.py` | Client config installation | Off-path; filesystem. |
| `copium/evals/`, `learn/`, `memory/` writers | Research / batch tooling | Off-path; long-running batch. |
| `copium/tokenizers/` | Parity backstop | Used only by parity harness if H3 keeps it. |
| `copium/telemetry/toin.py` | TOIN learning loop | Off-path; observation-only after Phase B PR-B5. |
| `copium/subscription/tracker.py`, `client.py` | Subscription usage poller | Off-path. |
| `copium/copilot_auth.py` | Copilot OAuth refresh | Off-path; specific to Copilot integration. |

## Phase H acceptance summary

After all 3 PRs land:

- ✅ Python proxy server retired
- ✅ All Python proxy handlers deleted
- ✅ Memory subsystem refactored or deleted
- ✅ LiteLLM backend retired
- ✅ Operators run only the Rust `copium-proxy` binary
- ✅ ~20 K LOC of Python deleted
- ✅ Migration guide for operators

**Phase H is the deletion. The OSS surface area shrinks dramatically; maintenance debt drops; behavior becomes consistent across deployments.**
