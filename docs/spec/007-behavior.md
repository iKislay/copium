# 007. Behavior

**Status:** done

## Proxy Modes

### Passthrough

Copium forwards requests without modification.

**Behavior:**
- All requests pass through unchanged
- Response headers may be modified for telemetry
- No compression applied
- Useful for testing or debugging

**Configuration:** `copium proxy --no-optimize`

**Request Flow:**
```
Client → Proxy → Provider API → Response
```

---

### Token Mode

Copium applies deterministic transforms to requests.

**Behavior:**
- SmartCrusher compresses JSON tool outputs
- CacheAligner stabilizes prefixes
- RollingWindow caps context tokens
- CCR caching enabled
- Token budget enforced

**Configuration:** `COPIUM_MODE=token` or `copium proxy --mode token`

**Request Flow:**
```
Client → Proxy → [SmartCrusher] → [CacheAligner]
         → [RollingWindow] → [CCR Cache]
         → Provider API → Response
```

---

### Cache Mode

Copium preserves prior turns where possible to maximize provider prefix-cache hit rate.

**Behavior:**
- Freezes provider-confirmed cached prefixes
- Compresses the mutable tail of the request
- Trades some token savings for better cache stability

**Configuration:** `COPIUM_MODE=cache` or `copium proxy --mode cache`

---

## Session Modes

Session modes control how Copium handles context windows.

| Mode | Description | Use Case |
|------|-------------|----------|
| `token` | Prioritize token removal | Default proxy mode |
| `cache` | Preserve prior turns for provider prefix-cache stability | Long Claude/Codex sessions |
| passthrough | Disable optimization with `--no-optimize` | Debugging |

---

## Request Lifecycle

```
1. Request received at proxy endpoint
   │
   ▼
2. Session lookup/creation
   │  - Extract session ID from headers
   │  - Create new session if not found
   │
   ▼
3. Mode determination
   │  - Check COPIUM_MODE
   │  - Check runtime headers
   │  - Determine active plugins
   │
   ▼
4. Compression pipeline execution
   │  a. Token counting
   │  b. Semantic cache check
   │  c. Content type detection
   │  d. Transform selection
   │  e. Summary compression (if eligible)
   │  f. Token budget enforcement
   │
   ▼
5. Forward to provider API
   │  - Route to correct provider
   │  - Apply API key from config
   │  - Handle timeouts
   │
   ▼
6. Response capture
   │  - Log request/response metadata
   │  - Calculate savings
   │
   ▼
7. Savings calculation
   │  - tokens_before - tokens_after
   │  - percentage = savings / tokens_before
   │
   ▼
8. Telemetry emission
   │  - Prometheus metrics
   │  - Optional tracing
   │
   ▼
9. Response returned to client
      - X-Copium-Savings header
      - X-Copium-Original-Tokens header
      - X-Copium-Compressed-Tokens header
```

---

## Error Handling

| Error Type | HTTP Code | Behavior |
|------------|----------|----------|
| Provider timeout | 504 | Retry up to 3 times with exponential backoff |
| Invalid request | 400 | Return error details in body |
| Compression failure | 500 | Fall back to passthrough mode |
| Provider error | Provider code | Return provider error to client |
| Internal error | 500 | Return 500, log details |
| Rate limited | 429 | Return retry-after header |

**Retry Configuration:**
```python
@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
```

---

## Response Headers

Copium adds headers to all compressed responses:

```
X-Copium-Savings: 0.35
X-Copium-Original-Tokens: 8192
X-Copium-Compressed-Tokens: 5325
X-Copium-Compression-Type: semantic,summary
X-Copium-Request-Id: abc123
X-Copium-Cache-Hit: false
```

**Header Descriptions:**
- `X-Copium-Savings` — Token savings percentage (0.35 = 35%)
- `X-Copium-Original-Tokens` — Token count before compression
- `X-Copium-Compressed-Tokens` — Token count after compression
- `X-Copium-Compression-Type` — Types of compression applied
- `X-Copium-Request-Id` — Unique request identifier
- `X-Copium-Cache-Hit` — Whether result was from cache

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-draft | 2026-04-16 | Initial behavior document |
