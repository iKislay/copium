# Agent Context Management (Smart Zone)

This document summarizes the new agent-aware context lifecycle implementation.

## Highlights

- Smart Zone budgeting with model/task/quantization factors.
- Phase-aware compression strategies.
- Value-based compression prioritization.
- Orientation cache for faster first-turn effectiveness.
- Session health monitoring with warnings and recommendations.

## Core Package

`copium/agent_context/`

## Test Suite

`tests/test_agent_context/`

## Recommended Next Integrations

- MCP tools for `copium_agent_context_status` and `copium_orientation_cache`
- Proxy hooks for proactive compaction prevention
- CLI surface for `copium run --agent-mode`