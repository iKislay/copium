"""Copium MCP Proxy — Transparent compression layer for MCP servers.

The MCP proxy sits between AI coding tools (Claude Code, Cursor, Codex) and
upstream MCP servers, transparently compressing tool descriptions, schemas,
and responses. Think of it as a CDN for MCP — one proxy, all servers,
70-90% fewer tokens.

Architecture:
    Agent → Copium MCP Proxy → Upstream MCP Servers

Features:
    - Tool description compression (70-90% reduction)
    - Schema compression via existing SchemaCompressor (~57% reduction)
    - Response compression via ContentRouter (60-95% reduction)
    - Session-level deduplication (95-99% on repeated definitions)
    - Progressive tool disclosure (99% reduction on tool definitions)
    - CCR retrieval for full response recovery

Quick Start:
    # Start the proxy with upstream servers
    copium mcp proxy serve

    # Install into Claude Code / Cursor / Codex
    copium mcp proxy install --agent claude-code

Usage:
    from copium.mcp_proxy import ProxyConfig, CopiumMCPProxy

    config = ProxyConfig.from_file("~/.copium/mcp-proxy.yaml")
    proxy = CopiumMCPProxy(config)
    await proxy.serve()
"""

from copium.mcp_proxy.config import ProxyConfig, UpstreamServerConfig
from copium.mcp_proxy.description_compressor import DescriptionCompressor
from copium.mcp_proxy.response_compressor import ResponseCompressor
from copium.mcp_proxy.session_dedup import SessionDedup

__all__ = [
    "CopiumMCPProxy",
    "DescriptionCompressor",
    "ProxyConfig",
    "ResponseCompressor",
    "SessionDedup",
    "UpstreamServerConfig",
]


def __getattr__(name: str):
    """Lazy import for CopiumMCPProxy to avoid loading MCP SDK eagerly."""
    if name == "CopiumMCPProxy":
        from copium.mcp_proxy.proxy import CopiumMCPProxy

        return CopiumMCPProxy
    raise AttributeError(f"module 'copium.mcp_proxy' has no attribute {name!r}")
