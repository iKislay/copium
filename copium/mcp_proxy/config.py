"""Configuration for the Copium MCP Proxy.

Defines ProxyConfig (top-level) and UpstreamServerConfig (per-server)
data classes. Supports loading from YAML/JSON files and environment
variables.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UpstreamServerConfig:
    """Configuration for a single upstream MCP server."""

    name: str
    """Logical name for the server (e.g. 'filesystem', 'github')."""

    command: str
    """Command to launch the server (e.g. 'npx')."""

    args: list[str] = field(default_factory=list)
    """Arguments passed to the command."""

    env: dict[str, str] = field(default_factory=dict)
    """Additional environment variables for the server process."""

    transport: str = "stdio"
    """Transport type: 'stdio' or 'http'."""

    url: str | None = None
    """URL for HTTP transport servers."""

    enabled: bool = True
    """Whether this server is active."""


@dataclass
class CompressionConfig:
    """Compression settings for the proxy."""

    descriptions: bool = True
    """Compress tool descriptions (70-90% reduction)."""

    schemas: bool = True
    """Compress tool schemas (~57% reduction)."""

    responses: bool = True
    """Compress tool call responses (60-95% reduction)."""

    progressive_disclosure: bool = True
    """Use progressive tool disclosure (stubs first, full on demand)."""

    session_dedup: bool = True
    """Deduplicate repeated tool definitions across turns."""

    min_response_tokens: int = 100
    """Minimum response size (tokens) before compression kicks in."""

    max_description_tokens: int = 50
    """Target max tokens per compressed tool description."""


@dataclass
class ProxyConfig:
    """Top-level configuration for the Copium MCP Proxy."""

    upstream_servers: list[UpstreamServerConfig] = field(default_factory=list)
    """List of upstream MCP servers to proxy."""

    compression: CompressionConfig = field(default_factory=CompressionConfig)
    """Compression settings."""

    cache_ttl_seconds: int = 300
    """TTL for cached tool schemas (seconds)."""

    debug: bool = False
    """Enable debug logging."""

    metrics_enabled: bool = True
    """Collect and expose compression metrics."""

    ccr_enabled: bool = True
    """Store originals in CCR for retrieval."""

    @classmethod
    def from_file(cls, path: str | Path) -> ProxyConfig:
        """Load config from a JSON or YAML file."""
        path = Path(path).expanduser()
        if not path.exists():
            return cls()

        text = path.read_text()

        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml

                data = yaml.safe_load(text) or {}
            except ImportError:
                raise ImportError(
                    "PyYAML is required for YAML config files. "
                    "Install with: pip install pyyaml"
                )
        else:
            data = json.loads(text)

        return cls._from_dict(data)

    @classmethod
    def from_env(cls) -> ProxyConfig:
        """Load config from environment variables."""
        config_path = os.environ.get("COPIUM_PROXY_CONFIG")
        if config_path:
            return cls.from_file(config_path)
        return cls()

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> ProxyConfig:
        """Parse a config dictionary into ProxyConfig."""
        servers = []
        for name, server_data in data.get("upstream_servers", {}).items():
            if isinstance(server_data, dict):
                servers.append(
                    UpstreamServerConfig(
                        name=name,
                        command=server_data.get("command", ""),
                        args=server_data.get("args", []),
                        env=server_data.get("env", {}),
                        transport=server_data.get("transport", "stdio"),
                        url=server_data.get("url"),
                        enabled=server_data.get("enabled", True),
                    )
                )

        compression_data = data.get("compression", {})
        compression = CompressionConfig(
            descriptions=compression_data.get("descriptions", True),
            schemas=compression_data.get("schemas", True),
            responses=compression_data.get("responses", True),
            progressive_disclosure=compression_data.get("progressive_disclosure", True),
            session_dedup=compression_data.get("session_dedup", True),
            min_response_tokens=compression_data.get("min_response_tokens", 100),
            max_description_tokens=compression_data.get("max_description_tokens", 50),
        )

        return cls(
            upstream_servers=servers,
            compression=compression,
            cache_ttl_seconds=data.get("cache_ttl_seconds", 300),
            debug=data.get("debug", False),
            metrics_enabled=data.get("metrics_enabled", True),
            ccr_enabled=data.get("ccr_enabled", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to a dictionary."""
        servers = {}
        for s in self.upstream_servers:
            servers[s.name] = {
                "command": s.command,
                "args": s.args,
                "env": s.env,
                "transport": s.transport,
                "url": s.url,
                "enabled": s.enabled,
            }

        return {
            "upstream_servers": servers,
            "compression": {
                "descriptions": self.compression.descriptions,
                "schemas": self.compression.schemas,
                "responses": self.compression.responses,
                "progressive_disclosure": self.compression.progressive_disclosure,
                "session_dedup": self.compression.session_dedup,
                "min_response_tokens": self.compression.min_response_tokens,
                "max_description_tokens": self.compression.max_description_tokens,
            },
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "debug": self.debug,
            "metrics_enabled": self.metrics_enabled,
            "ccr_enabled": self.ccr_enabled,
        }

    def save(self, path: str | Path) -> None:
        """Save config to a JSON file."""
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
