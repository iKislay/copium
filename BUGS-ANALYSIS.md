# Bug Analysis: Dashboard & Compression Issues

## Bug 1: Lifetime Savings < Session Savings (Dashboard Display)

### Root Cause
The "Session" column in the comparison table (line 1028, 1038, 1048 of `dashboard.html`) mixes two different data sources:
- `stats.tokens?.proxy_compression_saved` → **in-memory** Prometheus counter (resets on proxy restart)
- `stats.persistent_savings?.display_session?.tokens_saved` → **persisted** session value (survives restart)

The "Lifetime" column uses `stats.persistent_savings?.lifetime?.tokens_saved` (persisted).

When the display session expires (60 min inactivity), `_display_session_snapshot_locked()` returns `_empty_display_session()` (all zeros). But `stats.tokens?.proxy_compression_saved` is the in-memory counter which doesn't reset. This creates a mismatch where the session column shows a non-zero in-memory value while the lifetime column shows the persisted value.

Additionally, `stats.tokens?.saved` includes BOTH proxy compression AND CLI filtering tokens, while `persistent_savings?.lifetime?.tokens_saved` only tracks proxy compression. This makes the session total appear larger than lifetime.

### Fix Locations
- `/home/kislay/Desktop/coding/copium/copium/proxy/server.py` (lines 2567-2594): Align session/lifetime data sources
- `/home/kislay/Desktop/coding/copium/copium/dashboard/templates/dashboard.html` (lines 1017-1050): Use consistent data sources for comparison table

---

## Bug 2: CLI Filtering, Output Shaping, Prefix Cache Discount Don't Work with OpenCode Models

### Root Cause — Prefix Cache Discount
In `/home/kislay/Desktop/coding/copium/copium/proxy/cost.py` (lines 147-158), the `build_prefix_cache_stats()` function matches models to providers using hardcoded prefixes:
```python
_openai_prefixes = ("gpt", "o1", "o3", "o4")
is_match = (provider == "openai" and any(p in model_name for p in _openai_prefixes))
```
OpenCode Go models (`mimo-v2.5`, `glm-5.2`, `kimi-k2.7-code`, etc.) don't match any of these prefixes. So `input_price_per_token` stays `None`, and no dollar savings are calculated. The prefix cache discount bar shows $0.

### Root Cause — Output Shaping
Output shaping (`shape_request`) is ONLY called in the Anthropic handler (`anthropic.py:1742`). OpenCode models use OpenAI-format requests, so they never go through the Anthropic handler. Output shaping is not implemented for OpenAI-format requests.

### Root Cause — CLI Filtering
CLI filtering (RTK/lean-ctx) is model-agnostic — it runs outside the proxy at the shell level. The stats are collected globally. However, the dashboard "Savings by Layer" bar for CLI filtering (line 922) binds to `cliSavedTokens` which comes from `data.tokens?.cli_filtering_saved`. If RTK/lean-ctx is not installed or not wrapped, this value is 0 for ALL models, not just OpenCode.

### Fix Locations
- `/home/kislay/Desktop/coding/copium/copium/proxy/cost.py` (lines 147-158): Add OpenCode model name matching for prefix cache stats
- `/home/kislay/Desktop/coding/copium/copium/proxy/handlers/openai.py`: Implement output shaping for OpenAI-format requests (or document as not applicable)

---

## Bug 3: Recent Request Log Always Empty

### Root Cause
The `RequestLogger` is only created when `config.log_requests` is `True` (server.py:710). If `log_requests` is `False`, `self.logger` is `None`, and `emit_request_outcome()` skips logging entirely (outcome.py:394-395).

The dashboard's `_build_recent_request_payload()` (server.py:2422-2447) returns empty arrays when `proxy.logger` is `None`:
```python
recent_request_logs = proxy.logger.get_recent(limit) if proxy.logger else []
```

Additionally, the filter at lines 2441-2442 excludes entries where `input_tokens_original` or `input_tokens_optimized` is `None`:
```python
if log.get("input_tokens_original") is not None
and log.get("input_tokens_optimized") is not None
```
Cache-hit outcomes have `original_tokens=0` and `optimized_tokens=0`, which would pass this filter. But if the logger is `None`, nothing is logged at all.

### Fix Location
- `/home/kislay/Desktop/coding/copium/copium/proxy/server.py` (line 710): Ensure `log_requests` defaults to `True` or provide clear UI indication when logging is disabled
- `/home/kislay/Desktop/coding/copium/copium/dashboard/templates/dashboard.html`: Show a message when request logging is disabled

---

## Bug 4: Compression Sometimes Doesn't Happen

### Root Cause
The `CompressionDecision.decide()` method (compression_decision.py:118-138) checks:
1. `bypass` header → skip
2. `config.optimize` is False → skip
3. Empty messages → skip
4. License check → skip

If `config.optimize` is `False`, compression is skipped for ALL requests. This is a configuration issue, not a code bug. The user should verify their config.

Additionally, the bypass header `x-copium-bypass: true` or `x-copium-mode: passthrough` can be sent by the client (opencode), which would skip compression.

### Fix Location
- `/home/kislay/Desktop/coding/copium/copium/proxy/compression_decision.py`: Add logging when compression is skipped so users can diagnose
