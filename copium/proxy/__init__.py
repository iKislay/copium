"""Copium Proxy Server.

A transparent proxy that sits between LLM clients (Claude Code, Cursor, etc.)
and LLM APIs (Anthropic, OpenAI), applying Copium optimizations.

Usage:
    # Start the proxy
    python -m copium.proxy.server

    # Use with Claude Code
    ANTHROPIC_BASE_URL=http://localhost:8787 claude

    # Use with Cursor (if using Anthropic)
    Set base URL in Cursor settings to http://localhost:8787
"""

__all__ = [
    "CompactionDetector",
    "PostCompactRecovery",
    "PreCompactHook",
    "create_app",
    "run_server",
]


def __getattr__(name: str) -> object:
    if name in ("create_app", "run_server"):
        from .server import create_app, run_server  # noqa: F811

        globals()["create_app"] = create_app
        globals()["run_server"] = run_server
        return globals()[name]
    if name == "CompactionDetector":
        from .compaction_detector import CompactionDetector  # noqa: F811

        globals()["CompactionDetector"] = CompactionDetector
        return CompactionDetector
    if name == "PreCompactHook":
        from .pre_compact_hook import PreCompactHook  # noqa: F811

        globals()["PreCompactHook"] = PreCompactHook
        return PreCompactHook
    if name == "PostCompactRecovery":
        from .post_compact_recovery import PostCompactRecovery  # noqa: F811

        globals()["PostCompactRecovery"] = PostCompactRecovery
        return PostCompactRecovery
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
