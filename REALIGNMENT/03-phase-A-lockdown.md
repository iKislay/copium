# Phase A — Cache-Safety Lockdown

**Goal:** Stop the cache-killer bleeding tonight. Each PR is small, low-risk, independently reversible. Zero new architecture; minimum viable fixes only.

**Calendar:** 1 week. PR-A1 lands today; A2–A8 over the week.

**Shape:** 8 PRs, each on its own branch, each in its own worktree. Sequential dependency only between A1→A4; the rest are parallelizable.

---

## PR-A1 — Make `/v1/messages` compression a passthrough

**Branch:** `realign-A1-icm-passthrough`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A1-icm-passthrough`
**Risk:** **LOW** (deletion + tests; no new logic)
**LOC:** -180 / +30

### Scope
Stop calling ICM from the Rust proxy on `/v1/messages`. The proxy becomes a pure byte-faithful passthrough on this endpoint. Zero compression value temporarily, but eliminates the C1+C2+C3+C4 cache-killer cluster (P0-3, P0-4, P0-5, P1-13). Compression returns in Phase B.

### Files

**Delete:**
- `crates/copium-proxy/src/compression/icm.rs`

**Modify:**
- `crates/copium-proxy/src/compression/mod.rs` — remove `pub mod icm;`, remove ICM dispatch in `maybe_compress`. The `is_compressible_path` check still matches `/v1/messages` but `compress_anthropic_request` becomes a no-op stub returning `Outcome::NoCompression`.
- `crates/copium-proxy/src/compression/anthropic.rs` — replace function body with `Ok(Outcome::NoCompression)`. Keep the function signature so callers compile; subsequent PRs in Phase B replace this with the live-zone block dispatcher.
- `crates/copium-proxy/src/proxy.rs` — confirm the `Outcome::NoCompression` branch forwards original bytes (already does at line 296-298; just verify with the new test).

**Tests added:**
- `crates/copium-proxy/tests/integration_compression.rs::compression_on_message_passes_body_unchanged_sha256` — record a real Anthropic request body to a fixture; send through proxy; assert SHA-256 of upstream-received body equals SHA-256 of inbound body.

**Tests deleted/updated:**
- Update `compression_on_short_body_passes_through` to assert SHA-256 byte-equality (not just `len()`).
- Update `compression_on_long_body_drops_messages` — rename to `compression_on_long_body_passes_through_in_phase_A`. The old assertion (fewer messages arrived) becomes the opposite (same messages arrive).

### Acceptance criteria

- `cargo test -p copium-proxy` green.
- New SHA-256 round-trip test passes.
- The proxy still starts and serves `/healthz`.
- `make ci-precheck` green.

### Blocked by

None. Land first.

### Blocks

PR-A4 (cache_control honoring needs the ICM call site removed first to avoid conflict).
All Phase B PRs (which delete the surrounding code).

### Rollback

`git revert` the merge commit. ICM is restored. (Note: this also restores P0-3 and P0-4. Acceptable for ~hours during emergency rollback.)

### Notes

- The `compress_anthropic_request` function stays as a stub so Phase B has a single rewrite target.
- This PR does NOT delete ICM the module yet — `crates/copium-core/src/context/manager.rs` still compiles. PR-B1 deletes the modules. Splitting keeps the diff scoped.

---

## PR-A2 — Stop mutating the system prompt; route memory context to live zone

**Branch:** `realign-A2-system-prompt-immutable`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A2-system-prompt-immutable`
**Risk:** **MEDIUM** (touches memory feature behavior)
**LOC:** -150 / +80

### Scope
Eliminate P0-1 and P2-23. The system prompt is never mutated; memory context is appended to the latest user message tail (live zone). Delete the cache_aligner rewrite path; keep the volatile-content detector for warnings only.

### Files

**Modify:**
- `copium/proxy/server.py:1026-1071` — delete `_inject_system_context`. Memory context handling routes exclusively through `_append_context_to_latest_non_frozen_user_turn` (already exists at `handlers/anthropic.py:1117-1135` for cache mode; promote to default).
- `copium/proxy/handlers/openai.py:1212` — same: delete `body["instructions"] = f"{existing_instructions}\n\n{memory_context}"`. Replace with append-to-latest-user-message-tail.
- `copium/transforms/cache_aligner.py` — delete the rewrite path (lines 160-262). Keep the volatile-content detector and the `cache_aligner_warnings` callback that surfaces detected dynamic content (UUIDs, dates, tokens) to a customer-visible log line.
- `copium/proxy/server.py:299` — `cache_aligner.enabled` flag stays default-False; document that turning it on now only affects warnings.

**Tests added:**
- `tests/test_proxy_system_prompt_immutable.py::test_memory_enabled_does_not_mutate_system` — request with memory enabled; assert outbound system bytes equal inbound system bytes.
- `tests/test_proxy_system_prompt_immutable.py::test_memory_context_appears_in_user_tail` — same request; assert memory context appears in the last user message's tail.
- `tests/test_cache_aligner_detector_only.py::test_volatile_content_detected_warned_not_rewritten` — system prompt with UUID; assert detector emits warning log; assert system bytes unchanged.

**Tests deleted/updated:**
- `tests/test_cache_aligner_rewrite_*.py` — delete; rewrite path is gone.

### Acceptance criteria

- All new tests pass.
- Existing memory tests still pass (the live-zone-tail append should produce equivalent semantics).
- No regression in `tests/test_proxy_anthropic_cache_stability.py`.

### Blocked by

None. Parallel with A1.

### Blocks

PR-B6 (memory subsystem refactor, which builds on this).

### Rollback

`git revert` the merge commit. Memory injection returns to system prompt. P0-1 returns.

---

## PR-A3 — Switch Python forwarders to byte-faithful body forwarding

**Branch:** `realign-A3-byte-faithful-forwarders`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A3-byte-faithful-forwarders`
**Risk:** **HIGH** (touches every outbound HTTP call in Python)
**LOC:** -200 / +250

### Scope
Eliminate P0-2 universally. Every Python forwarder switches from `httpx ... json=body` to `httpx ... content=raw_bytes`. When body was mutated by a transform, re-serialize once with `separators=(",", ":")`, `ensure_ascii=False`, and the original encoding. When unmutated, forward the original `await request.body()` verbatim.

### Files

**Modify:**
- `copium/proxy/server.py:1073-1124` — `_retry_request`: track whether body was mutated; if not, forward `original_body_bytes`; if yes, re-serialize with the canonical settings. Switch `await self.http_client.post(url, json=body)` to `await self.http_client.post(url, content=outbound_bytes, headers={**headers, "content-type": "application/json"})`.
- `copium/proxy/handlers/streaming.py:617-660` — same pattern in `_send_streaming_request`.
- `copium/proxy/handlers/openai.py:2392-2410` — WS→HTTP fallback: same pattern.
- `copium/proxy/handlers/batch.py:340-360` — batch endpoint: same pattern.
- `copium/proxy/helpers.py` — add `serialize_body_canonical(body: dict) -> bytes` helper using `json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.

**Tests added:**
- `tests/test_proxy_byte_faithful_forwarding.py::test_passthrough_no_mutation_byte_equal` — request with no compression / memory / transforms; assert SHA-256 of upstream-received body equals SHA-256 of client-sent body.
- `tests/test_proxy_byte_faithful_forwarding.py::test_compression_off_unicode_preserved` — request with `🔥` and CJK chars in user message; assert no `\uXXXX` escaping at upstream.
- `tests/test_proxy_byte_faithful_forwarding.py::test_compression_off_numeric_precision_preserved` — request with `temperature: 1.0` and `seed: 12345678901234567`; assert exact bytes.

### Acceptance criteria

- New byte-faithful tests pass.
- Existing test suite green.
- Manual smoke test: send a real request through the proxy with `tcpdump` or a recording mock; verify the bytes hitting upstream match a direct-to-Anthropic baseline.

### Blocked by

None. Parallel with A1, A2.

### Blocks

PR-A6 (memory tool injection refactor relies on the new mutation-tracking helper).

### Rollback

`git revert`. The httpx `json=` defaults return.

### Notes

- This is the highest-impact single PR for cache hit rate. Test coverage carefully.
- `httpx.AsyncClient` defaults set Content-Length from the bytes; verify no Transfer-Encoding chunked drift.
- The `accept-encoding` header strip stays for now; Phase F PR-F2 makes it conditional on auth mode.

---

## PR-A4 — Honor customer `cache_control` markers in Rust; enable `arbitrary_precision`+`raw_value`

**Branch:** `realign-A4-honor-cache-control`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A4-honor-cache-control`
**Risk:** **MEDIUM** (Rust-only; tightly scoped)
**LOC:** -30 / +200

### Scope
Eliminate P0-3 and P0-5 directly. In Rust, walk customer-set `cache_control` markers in `system`, `tools`, and `messages`; compute the effective `frozen_message_count`. Switch `serde_json` to `arbitrary_precision` + `raw_value` features. Use `&RawValue` for `messages[*]` so unmodified messages forward as exact byte copies. The `compress_anthropic_request` function is currently a no-op stub (per A1) — this PR adds the cache_control parser as preparation for Phase B.

### Files

**Modify:**
- `Cargo.toml:34` — add features: `serde_json = { version = "1", features = ["preserve_order", "arbitrary_precision", "raw_value"] }`. Run `cargo update -p serde_json`.
- `crates/copium-proxy/src/compression/anthropic.rs` — add `pub fn compute_frozen_count(parsed: &serde_json::Value) -> usize` that walks `messages[*].content[*].cache_control`, `system[*].cache_control`, `tools[*].cache_control` and returns the highest message index whose content contains a marker. (Used by Phase B; currently called only by tests.)
- `crates/copium-core/src/lib.rs` — re-export `compute_frozen_count` for use in Phase B.

**Add:**
- `crates/copium-proxy/tests/integration_cache_control.rs::cache_control_marker_at_message_3_yields_frozen_count_3`
- `crates/copium-proxy/tests/integration_cache_control.rs::cache_control_in_system_blocks_yields_frozen_count_full_history`
- `crates/copium-proxy/tests/integration_cache_control.rs::cache_control_ttl_1h_before_5m_passes`
- `crates/copium-proxy/tests/integration_cache_control.rs::cache_control_ttl_5m_before_1h_warns_and_passes` (we don't reject, but log per §2.19 ordering rule)

### Acceptance criteria

- `cargo build -p copium-proxy` works with new features.
- `cargo test -p copium-proxy` green.
- The `compute_frozen_count` returns 0 for a request with zero markers; returns N for a request with a marker on `messages[N]`.

### Blocked by

PR-A1 (the call site needs to be removed before this can land cleanly).

### Blocks

PR-B2 (live-zone block dispatcher uses `compute_frozen_count`).

### Rollback

`git revert`. The Cargo features stay (harmless).

### Notes

- `RawValue` is enabled but not yet consumed in this PR. Phase B PR-B2 wires it.
- Per guide §2.19, `1h` markers must precede `5m` markers; we log a warning when the ordering is reversed but don't reject (the customer's request, not ours to validate).

---

## PR-A5 — Strip `x-copium-*` from upstream-bound headers

**Branch:** `realign-A5-strip-copium-headers`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A5-strip-copium-headers`
**Risk:** **LOW**
**LOC:** -10 / +50

### Scope
Eliminate P5-49. `dict(request.headers.items())` is captured unmodified and forwarded; this PR adds an explicit strip step before any upstream call. Reduces fingerprint surface for subscription detection.

### Files

**Modify:**
- `copium/proxy/handlers/anthropic.py:526` — wrap `dict(request.headers.items())` with `_strip_internal_headers(headers)` (new helper).
- `copium/proxy/handlers/openai.py:232-264` — same.
- `copium/proxy/handlers/streaming.py:617` — same.
- `copium/proxy/handlers/batch.py:340` — same.
- `copium/proxy/handlers/gemini.py:31` — same.
- `copium/proxy/helpers.py` — add `_strip_internal_headers` helper. Default strip list: `x-copium-*` (case-insensitive prefix), plus a hardcoded set of internal flags.
- `crates/copium-proxy/src/headers.rs` — add `strip_internal_headers` to the request-side filter. Document that response-side `X-Copium-*` injection (which is fine) is unrelated.

**Tests added:**
- `tests/test_header_isolation.py::test_x_copium_bypass_not_forwarded`
- `tests/test_header_isolation.py::test_x_copium_mode_not_forwarded`
- `tests/test_header_isolation.py::test_x_copium_user_id_not_forwarded`
- `crates/copium-proxy/tests/integration_headers.rs::x_copium_request_headers_stripped`

### Acceptance criteria

- New tests pass.
- Existing client-driven `x-copium-bypass: true` flow still works (proxy reads it; just doesn't forward).
- No legitimate header is stripped (whitelist `x-request-id`, `x-trace-id`, etc. by default — though they aren't `x-copium-*` so they're untouched).

### Blocked by

None. Parallel.

### Blocks

PR-F2 (auth-mode policy uses this helper).

### Rollback

`git revert`. Headers leak again. Low operational risk.

---

## PR-A6 — Pin `anthropic-beta` order; session-stickiness skeleton

**Branch:** `realign-A6-anthropic-beta-stable`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A6-anthropic-beta-stable`
**Risk:** **MEDIUM** (touches memory injection beta-mutation)
**LOC:** -40 / +180

### Scope
Eliminate P5-50 and start P5-51. When the proxy mutates `anthropic-beta` (memory injection), the new comma-list is computed deterministically (sort tokens or preserve insertion order with new tokens appended). Add a per-session "betas seen so far" tracker so any beta seen in turn N is included in turn N+1 even if the client drops it.

### Files

**Modify:**
- `copium/proxy/handlers/anthropic.py:1162-1168` — replace the ad-hoc concat with a helper `merge_anthropic_beta(client: str, copium: list[str]) -> str` that splits client's value on `,`, lowercases each token, deduplicates, appends Copium-required tokens (sorted within the appended group), and rejoins.
- `copium/proxy/server.py` — extend `session_state` (already exists for memory) to track `betas_seen: set[str]` per session. Update on every request; merge into outbound `anthropic-beta` for follow-up requests.
- `copium/proxy/helpers.py` — add `betas_seen_lock` and `update_session_betas` helpers.

**Tests added:**
- `tests/test_anthropic_beta_session_sticky.py::test_beta_seen_turn_1_present_in_turn_2_even_if_client_drops`
- `tests/test_anthropic_beta_session_sticky.py::test_memory_injection_appends_deterministic_order`
- `tests/test_anthropic_beta_session_sticky.py::test_client_value_preserved_when_no_injection`

### Acceptance criteria

- New tests pass.
- Session ID is keyed off the existing session detection (per `copium/proxy/handlers/anthropic.py:1417`).
- The "betas seen" set is bounded (LRU eviction at 1000 sessions).

### Blocked by

PR-A3 (relies on byte-faithful forwarder for header-bytes correctness; if A3 is rolled back, this still works but is less effective).

### Blocks

PR-A7 (memory tool session-stickiness uses the same session-state plumbing).

### Rollback

`git revert`. Beta header drift returns; functional but degraded cache safety.

---

## PR-A7 — Memory tool injection session-sticky

**Branch:** `realign-A7-memory-tool-sticky`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A7-memory-tool-sticky`
**Risk:** **MEDIUM**
**LOC:** -30 / +150

### Scope
Eliminate the rest of P0-6. Once memory injects a tool into `body["tools"]` for a session, every subsequent request in that session also injects the same tool (same name, same definition bytes). Toggling off mid-session is forbidden.

### Files

**Modify:**
- `copium/proxy/memory_tool_adapter.py:625-657` — make injection session-state-aware. The session-state object grows a `memory_tools_injected: bool` and `memory_tools_definition_bytes: bytes` (golden form). On every request: if previously injected, inject again with byte-equal definition.
- `copium/proxy/memory_handler.py:389-398` — same: native-tool path becomes session-sticky.
- `copium/proxy/handlers/anthropic.py:1147-1171` — read session state; either inject all (if previously injected or memory enabled this turn) or none.

**Tests added:**
- `tests/test_memory_tool_session_sticky.py::test_injection_in_turn_1_repeats_in_turn_2`
- `tests/test_memory_tool_session_sticky.py::test_byte_equal_tool_definition_across_turns`
- `tests/test_memory_tool_session_sticky.py::test_memory_disabled_after_inject_still_injects`

### Acceptance criteria

- New tests pass.
- The injected `memory_*` tool definitions are byte-stable across deploys (snapshot test pins the bytes).

### Blocked by

PR-A6.

### Blocks

PR-B6 (memory subsystem refactor).

### Rollback

`git revert`. Toggling returns. P0-6 returns.

---

## PR-A8 — Hotfix Python wire-format bugs; add SHA-256 round-trip test

**Branch:** `realign-A8-python-wire-hotfix`
**Worktree:** `~/claude-projects/copium-worktrees/realign-A8-python-wire-hotfix`
**Risk:** **MEDIUM**
**LOC:** -100 / +400

### Scope
Catch-all for the Python wire-format bugs that should be fixed before Phase H deletes the Python proxy. Specifically:
- P1-8: SSE byte-level decoding in `streaming.py` and `ccr/response_handler.py`.
- P1-9: Add `thinking_delta`, `signature_delta`, `citations_delta` arms to `_parse_sse_to_response`.
- P0-7 / P4-44: Preserve `phase` field in `responses_converter.py`; fix multi-text-part rebuild.
- P5-57 / P5-59: Capture upstream `request-id` in logs; fix body-size-cap status code (400 → 413).
- P4-47: Add a warning log line when `responses_converter.py:99` hits an unknown item type.
- P6-63: New SHA-256 byte-faithful round-trip test on a recorded production payload.

### Files

**Modify:**
- `copium/proxy/handlers/streaming.py:213-298` — rewrite `_parse_sse_to_response` to handle all delta types per guide §5.1. Add index-keyed block map. Bytes-level SSE buffer.
- `copium/proxy/handlers/streaming.py:58, 772` — switch `chunk.decode("utf-8", errors="ignore")` to a bytes-buffer + decode-after-`\n\n` pattern.
- `copium/ccr/response_handler.py:665-686` — same pattern.
- `copium/proxy/responses_converter.py:94, 235` — preserve `phase` explicitly. Fix multi-text-part rebuild: rebuild parts by index, replacing each part's text in place.
- `copium/proxy/responses_converter.py:99` — add `logger.warning(f"unknown responses item type: {item.get('type')}")`.
- `crates/copium-proxy/src/proxy.rs:355-358` — capture upstream `request-id` (Anthropic) and `x-request-id` (OpenAI) into the tracing field.
- `crates/copium-proxy/src/proxy.rs:243-263` — return 413 on body-too-large; return 400 only on actual parse error.

**Add:**
- `tests/fixtures/anthropic_messages_request_real.json` — recorded production-shaped payload (sanitized).
- `tests/test_proxy_byte_faithful_round_trip.py::test_sha256_round_trip_no_compression` — boot proxy; send fixture; assert SHA-256 byte-equal at upstream mock.
- `tests/test_proxy_responses_phase_preservation.py::test_codex_phase_commentary_preserved`
- `tests/test_proxy_responses_phase_preservation.py::test_codex_phase_final_answer_preserved`
- `tests/test_sse_thinking_blocks.py::test_thinking_delta_accumulated`
- `tests/test_sse_thinking_blocks.py::test_signature_delta_preserved`
- `tests/test_sse_thinking_blocks.py::test_citations_delta_accumulated`
- `tests/test_sse_utf8_split.py::test_emoji_split_across_chunks_preserved`
- `crates/copium-proxy/tests/integration_request_id.rs::upstream_request_id_captured`

### Acceptance criteria

- All new tests pass.
- Pre-existing test suite green.
- Manual streaming smoke test with thinking blocks + signatures.

### Blocked by

None. Parallel with A2-A7.

### Blocks

None directly; Phase C builds on the Rust SSE work but doesn't depend on this Python fix.

### Rollback

`git revert`. Wire-format bugs return; subsequent Phase C will re-fix in Rust anyway.

### Notes

- This is a "hotfix the Python proxy enough to be safe until Phase H deletes it" PR. Not investing in pretty Python here — just safety.
- The recorded fixture in `tests/fixtures/anthropic_messages_request_real.json` should include: thinking + signature blocks, tool_use with non-trivial JSON input, mixed-key schemas, non-ASCII content, large numbers, `cache_control` markers in messages and system.

---

## Phase A acceptance summary

After all 8 PRs land:

- ✅ ICM no longer drops messages from cache hot zone
- ✅ Customer `cache_control` markers honored in Rust
- ✅ System prompt never mutated
- ✅ Memory context routes to live-zone tail
- ✅ Memory tool injection session-sticky
- ✅ `anthropic-beta` mutation deterministic + session-sticky
- ✅ Python forwarders byte-faithful
- ✅ `x-copium-*` stripped from upstream
- ✅ Numeric precision preserved (RawValue + arbitrary_precision)
- ✅ SSE thinking/signature/citations deltas handled
- ✅ Codex `phase` preserved
- ✅ Upstream request-id captured
- ✅ SHA-256 byte-faithful round-trip test gating CI

**Phase A retires P0-1 through P0-7 and P1-8, P1-9, P5-49, P5-50, P5-57, P5-59, P6-63.**
