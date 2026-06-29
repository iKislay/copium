# Agent Context Management

Copium now includes a Smart Zone based agent context framework in `copium/agent_context/`.

## What It Solves

- Reduces orientation tax from repeated `list_dir`/`read_file`/`grep` loops.
- Keeps context usage within a model-safe Smart Zone budget.
- Applies phase-aware compression across the agent lifecycle.
- Adds health reporting and recommendations for long sessions.

## Modules

- `phase_detector.py`: Detects orientation, exploration, implementation, verification.
- `smart_zone.py`: Computes Smart Zone budget and compression aggressiveness.
- `tool_call_classifier.py`: Classifies tool calls with value and compressibility scores.
- `context_lifecycle.py`: Orchestrates per-call compression decisions through session lifecycle.
- `compression_scheduler.py`: Selects transform pipelines by phase and content type.
- `orientation_cache.py`: Builds compact codebase maps to skip orientation tool calls.
- `context_health.py`: Tracks Smart Zone health, warnings, and recommendations.

## Usage Sketch

```python
from copium.agent_context import (
    ContextLifecycleManager,
    SmartZoneConfig,
)

manager = ContextLifecycleManager(
    config=SmartZoneConfig(
        context_window=200_000,
        model_family="claude-4",
        quantization="cloud",
        task_type="implementation",
    )
)

manager.on_session_start("session-1")

decision = manager.on_tool_call(
    tool_name="list_dir",
    arguments={"path": "."},
    result_tokens=1500,
    current_context_tokens=24_000,
)

print(decision.should_compress, decision.transforms)
```

## Testing

Test coverage is in `tests/test_agent_context/` and includes module-level tests for:

- Phase detection
- Smart Zone calculations
- Tool classification and priority
- Lifecycle decisions
- Compression scheduling
- Orientation cache building
- Health monitoring