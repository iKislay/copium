# RTK vs Copium Benchmark

Head-to-head comparison of compression ratios on identical inputs.

## Run

```bash
# Full report with verbose output
python -m benchmarks.rtk-vs-copium.bench_rtk_vs_copium

# As pytest (validates infrastructure)
pytest benchmarks/rtk-vs-copium/ -v
```

## What it measures

| Content Type | RTK Coverage | Copium Coverage |
|---|---|---|
| git status | ✓ (strips hints) | ✓ (quality-gated) |
| git diff | ✓ (strips context) | ✓ (semantic diff) |
| pytest output | ✓ (partial) | ✓ (error-focused) |
| grep results | ✓ (passthrough) | ✓ (relevance-ranked) |
| file reads | ✗ (not compressed) | ✓ (AST-based) |

## Key insight

RTK only compresses CLI stdout. File reads and search results pass through
unchanged. Copium compresses everything the LLM sees.
