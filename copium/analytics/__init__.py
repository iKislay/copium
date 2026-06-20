"""Visual Analytics for compression savings.

Generates charts and reports showing token distribution,
compression savings by content type, and cost analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AnalyticsData:
    """Data for analytics visualization."""

    # Token distribution by category
    token_distribution: dict[str, int] = field(default_factory=dict)

    # Compression savings by content type
    savings_by_type: dict[str, dict[str, int]] = field(default_factory=dict)

    # Cost analysis
    cost_before: float = 0.0
    cost_after: float = 0.0
    cost_saved: float = 0.0

    # Timeline data
    timestamps: list[str] = field(default_factory=list)
    savings_over_time: list[float] = field(default_factory=list)

    # Per-transform breakdown
    transform_savings: dict[str, int] = field(default_factory=dict)

    # Cache metrics
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0


class VisualAnalytics:
    """Generate visual analytics reports."""

    def __init__(self, data: AnalyticsData | None = None) -> None:
        self.data = data or AnalyticsData()

    def generate_text_report(self) -> str:
        """Generate a text-based report (no matplotlib required)."""
        lines = [
            "=" * 60,
            "COPIUM ANALYTICS REPORT",
            "=" * 60,
            "",
            "COST ANALYSIS",
            "-" * 40,
            f"  Cost before: ${self.data.cost_before:.4f}",
            f"  Cost after:  ${self.data.cost_after:.4f}",
            f"  Cost saved:  ${self.data.cost_saved:.4f}",
            f"  Savings:     {(self.data.cost_saved / self.data.cost_before * 100) if self.data.cost_before > 0 else 0:.1f}%",
            "",
            "TOKEN DISTRIBUTION",
            "-" * 40,
        ]

        total_tokens = sum(self.data.token_distribution.values())
        for category, tokens in sorted(self.data.token_distribution.items(), key=lambda x: -x[1]):
            pct = (tokens / total_tokens * 100) if total_tokens > 0 else 0
            bar = "#" * int(pct / 2)
            lines.append(f"  {category:<20} {tokens:>8,} ({pct:>5.1f}%) {bar}")

        lines.extend(["", "COMPRESSION BY CONTENT TYPE", "-" * 40])

        for content_type, metrics in self.data.savings_by_type.items():
            before = metrics.get("before", 0)
            after = metrics.get("after", 0)
            saved = before - after
            pct = (saved / before * 100) if before > 0 else 0
            lines.append(f"  {content_type:<20} {before:>8,} -> {after:>8,} ({pct:.1f}% saved)")

        if self.data.transform_savings:
            lines.extend(["", "PER-TRANSFORM SAVINGS", "-" * 40])
            for transform, saved in sorted(self.data.transform_savings.items(), key=lambda x: -x[1]):
                lines.append(f"  {transform:<30} {saved:>8,} tokens")

        if self.data.cache_hits > 0 or self.data.cache_misses > 0:
            lines.extend([
                "",
                "CACHE METRICS",
                "-" * 40,
                f"  Hits:    {self.data.cache_hits:,}",
                f"  Misses:  {self.data.cache_misses:,}",
                f"  Hit rate: {self.data.cache_hit_rate:.1f}%",
            ])

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def generate_html_report(self) -> str:
        """Generate an HTML report with embedded charts."""
        # Token distribution pie chart data
        labels = list(self.data.token_distribution.keys())
        values = list(self.data.token_distribution.values())
        total = sum(values) if values else 1

        # Build HTML
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Copium Analytics Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #2563eb; }}
        .metric {{ background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 10px 0; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #059669; }}
        .bar {{ height: 20px; background: #2563eb; border-radius: 4px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
    </style>
</head>
<body>
    <h1>Copium Analytics Report</h1>

    <div class="metric">
        <h3>Cost Savings</h3>
        <div class="metric-value">${self.data.cost_saved:.4f} saved</div>
        <p>From ${self.data.cost_before:.4f} to ${self.data.cost_after:.4f}</p>
    </div>

    <h2>Token Distribution</h2>
    <table>
        <tr><th>Category</th><th>Tokens</th><th>Percentage</th></tr>
"""

        for category, tokens in sorted(self.data.token_distribution.items(), key=lambda x: -x[1]):
            pct = (tokens / total * 100) if total > 0 else 0
            html += f'        <tr><td>{category}</td><td>{tokens:,}</td><td>{pct:.1f}%</td></tr>\n'

        html += """    </table>

    <h2>Compression by Content Type</h2>
    <table>
        <tr><th>Type</th><th>Before</th><th>After</th><th>Saved</th></tr>
"""

        for content_type, metrics in self.data.savings_by_type.items():
            before = metrics.get("before", 0)
            after = metrics.get("after", 0)
            saved = before - after
            pct = (saved / before * 100) if before > 0 else 0
            html += f'        <tr><td>{content_type}</td><td>{before:,}</td><td>{after:,}</td><td>{pct:.1f}%</td></tr>\n'

        html += """    </table>
</body>
</html>"""

        return html

    def save_report(self, path: Path, format: str = "text") -> None:
        """Save report to file."""
        if format == "html":
            content = self.generate_html_report()
        else:
            content = self.generate_text_report()

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    @classmethod
    def from_metrics_db(cls, db_path: Path | None = None) -> VisualAnalytics:
        """Create analytics from the metrics database."""
        if db_path is None:
            from copium.paths import workspace_dir
            db_path = workspace_dir() / "metrics.db"

        if not db_path.exists():
            return cls()

        import sqlite3
        conn = sqlite3.connect(str(db_path))

        # Get token distribution
        distribution = {}
        for row in conn.execute("""
            SELECT kind, SUM(tokens) as total
            FROM block_metrics
            GROUP BY kind
        """):
            distribution[row[0]] = row[1]

        # Get cost metrics
        cost_row = conn.execute("""
            SELECT
                SUM(cost_before) as total_before,
                SUM(cost_after) as total_after
            FROM request_metrics
        """).fetchone()

        # Get transform savings
        transform_savings = {}
        for row in conn.execute("""
            SELECT transform, SUM(tokens_before - tokens_after) as saved
            FROM transform_applied
            GROUP BY transform
        """):
            transform_savings[row[0]] = row[1]

        conn.close()

        data = AnalyticsData(
            token_distribution=distribution,
            cost_before=cost_row[0] or 0,
            cost_after=cost_row[1] or 0,
            cost_saved=(cost_row[0] or 0) - (cost_row[1] or 0),
            transform_savings=transform_savings,
        )

        return cls(data)
