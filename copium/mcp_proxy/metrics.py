"""Observability and metrics for the MCP proxy.

Collects compression metrics, generates session reports, and provides
data for dashboards. Shows users the concrete savings from the proxy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolMetric:
    """Metrics for a single tool's compression performance."""

    name: str
    server: str = ""
    calls: int = 0
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0
    dedup_hits: int = 0
    avg_latency_ms: float = 0.0

    @property
    def savings_percent(self) -> float:
        if self.total_original_tokens == 0:
            return 0.0
        return (
            (1 - self.total_compressed_tokens / self.total_original_tokens) * 100
        )


@dataclass
class SessionReport:
    """Summary report for a proxy session."""

    start_time: float
    end_time: float
    upstream_servers: int
    tools_discovered: int
    tools_used: int

    # Token breakdown
    description_original: int = 0
    description_compressed: int = 0
    schema_original: int = 0
    schema_compressed: int = 0
    response_original: int = 0
    response_compressed: int = 0
    dedup_saved: int = 0

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time

    @property
    def total_original(self) -> int:
        return (
            self.description_original
            + self.schema_original
            + self.response_original
        )

    @property
    def total_compressed(self) -> int:
        return (
            self.description_compressed
            + self.schema_compressed
            + self.response_compressed
        )

    @property
    def total_savings_percent(self) -> float:
        if self.total_original == 0:
            return 0.0
        return (1 - self.total_compressed / self.total_original) * 100

    @property
    def cost_without_proxy(self) -> float:
        """Estimated cost without proxy (Claude Sonnet pricing: $3/M input)."""
        return self.total_original * 3.0 / 1_000_000

    @property
    def cost_with_proxy(self) -> float:
        """Estimated cost with proxy."""
        return self.total_compressed * 3.0 / 1_000_000

    @property
    def cost_saved(self) -> float:
        return self.cost_without_proxy - self.cost_with_proxy

    def format_report(self) -> str:
        """Format a human-readable session report."""
        lines = [
            "Copium MCP Proxy — Session Report",
            "=" * 50,
            "",
            f"Upstream Servers:    {self.upstream_servers}",
            f"Tools Discovered:    {self.tools_discovered}",
            f"Tools Used:          {self.tools_used}",
            "",
            "Compression Breakdown:",
            f"  Tool Descriptions:  {self.description_original:,} → "
            f"{self.description_compressed:,} tokens "
            f"({self._pct(self.description_original, self.description_compressed)} saved)",
            f"  Tool Schemas:       {self.schema_original:,} → "
            f"{self.schema_compressed:,} tokens "
            f"({self._pct(self.schema_original, self.schema_compressed)} saved)",
            f"  Tool Responses:     {self.response_original:,} → "
            f"{self.response_compressed:,} tokens "
            f"({self._pct(self.response_original, self.response_compressed)} saved)",
            f"  Session Dedup:      {self.dedup_saved:,} tokens saved",
            "  " + "-" * 46,
            f"  Total:              {self.total_original:,} → "
            f"{self.total_compressed:,} tokens "
            f"({self.total_savings_percent:.0f}% saved)",
            "",
            "Cost Impact:",
            f"  Without Copium:  ${self.cost_without_proxy:.2f}",
            f"  With Copium:     ${self.cost_with_proxy:.2f}",
            f"  You saved:       ${self.cost_saved:.2f} "
            f"({self.total_savings_percent:.0f}%)",
        ]
        return "\n".join(lines)

    @staticmethod
    def _pct(original: int, compressed: int) -> str:
        if original == 0:
            return "0%"
        return f"{(1 - compressed / original) * 100:.0f}%"


class MetricsCollector:
    """Collects and aggregates proxy compression metrics."""

    def __init__(self) -> None:
        self._start_time = time.time()
        self._tool_metrics: dict[str, ToolMetric] = {}
        self._session_tokens = {
            "description_original": 0,
            "description_compressed": 0,
            "schema_original": 0,
            "schema_compressed": 0,
            "response_original": 0,
            "response_compressed": 0,
            "dedup_saved": 0,
        }
        self._upstream_servers = 0
        self._tools_discovered = 0
        self._tools_used: set[str] = set()

    def set_upstream_info(self, servers: int, tools: int) -> None:
        """Set upstream server and tool counts."""
        self._upstream_servers = servers
        self._tools_discovered = tools

    def record_description_compression(
        self, original_tokens: int, compressed_tokens: int
    ) -> None:
        """Record description compression metrics."""
        self._session_tokens["description_original"] += original_tokens
        self._session_tokens["description_compressed"] += compressed_tokens

    def record_schema_compression(
        self, original_tokens: int, compressed_tokens: int
    ) -> None:
        """Record schema compression metrics."""
        self._session_tokens["schema_original"] += original_tokens
        self._session_tokens["schema_compressed"] += compressed_tokens

    def record_response_compression(
        self,
        tool_name: str,
        original_tokens: int,
        compressed_tokens: int,
        latency_ms: float = 0.0,
    ) -> None:
        """Record response compression metrics for a tool call."""
        self._session_tokens["response_original"] += original_tokens
        self._session_tokens["response_compressed"] += compressed_tokens
        self._tools_used.add(tool_name)

        if tool_name not in self._tool_metrics:
            self._tool_metrics[tool_name] = ToolMetric(name=tool_name)

        metric = self._tool_metrics[tool_name]
        metric.calls += 1
        metric.total_original_tokens += original_tokens
        metric.total_compressed_tokens += compressed_tokens
        # Running average latency
        metric.avg_latency_ms = (
            (metric.avg_latency_ms * (metric.calls - 1) + latency_ms)
            / metric.calls
        )

    def record_dedup_hit(self, tokens_saved: int) -> None:
        """Record a deduplication hit."""
        self._session_tokens["dedup_saved"] += tokens_saved

    def get_report(self) -> SessionReport:
        """Generate a session report from collected metrics."""
        return SessionReport(
            start_time=self._start_time,
            end_time=time.time(),
            upstream_servers=self._upstream_servers,
            tools_discovered=self._tools_discovered,
            tools_used=len(self._tools_used),
            description_original=self._session_tokens["description_original"],
            description_compressed=self._session_tokens["description_compressed"],
            schema_original=self._session_tokens["schema_original"],
            schema_compressed=self._session_tokens["schema_compressed"],
            response_original=self._session_tokens["response_original"],
            response_compressed=self._session_tokens["response_compressed"],
            dedup_saved=self._session_tokens["dedup_saved"],
        )

    def get_tool_metrics(self) -> list[ToolMetric]:
        """Get per-tool metrics sorted by savings."""
        metrics = list(self._tool_metrics.values())
        metrics.sort(key=lambda m: m.total_original_tokens, reverse=True)
        return metrics

    @property
    def stats(self) -> dict[str, Any]:
        """Return metrics as a dictionary."""
        report = self.get_report()
        return {
            "uptime_seconds": round(report.duration_seconds, 1),
            "upstream_servers": self._upstream_servers,
            "tools_discovered": self._tools_discovered,
            "tools_used": len(self._tools_used),
            "total_original_tokens": report.total_original,
            "total_compressed_tokens": report.total_compressed,
            "savings_percent": round(report.total_savings_percent, 1),
            "cost_saved_usd": round(report.cost_saved, 4),
        }
