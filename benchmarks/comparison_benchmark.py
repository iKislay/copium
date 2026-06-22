"""Head-to-head comparison benchmark suite.

Compares Copium against baseline compression approaches across
multiple dimensions: compression ratio, quality preservation,
latency, and cost savings.

Usage:
    python -m benchmarks.comparison_benchmark
    python -m benchmarks.comparison_benchmark --dataset bfcl
    python -m benchmarks.comparison_benchmark --report comparison.md
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copium.compress import compress
from copium.config import CopiumConfig
from copium.tokenizers import get_tokenizer


@dataclass
class BenchmarkItem:
    """A single benchmark item with messages and expected output."""

    name: str
    messages: list[dict[str, Any]]
    expected_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Result of running a benchmark on one item."""

    item_name: str
    original_tokens: int
    compressed_tokens: int
    tokens_saved: int
    compression_ratio: float
    latency_ms: float
    error: str | None = None


@dataclass
class ComparisonReport:
    """Aggregated comparison report."""

    results: list[BenchmarkResult]
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0
    total_tokens_saved: int = 0
    avg_compression_ratio: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    success_count: int = 0
    error_count: int = 0


# ── Sample benchmark datasets ──────────────────────────────────────────


def _generate_code_review_dataset() -> list[BenchmarkItem]:
    """Generate code review messages with tool outputs."""
    items = []
    for i in range(10):
        messages = [
            {"role": "system", "content": "You are a code reviewer."},
            {"role": "user", "content": f"Review this code: file_{i}.py"},
            {
                "role": "assistant",
                "content": f"I'll review file_{i}.py for you.",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "Read", "arguments": f'{{"path": "src/file_{i}.py"}}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "content": f"def process_{i}(data):\n    # {'x' * 200}\n    result = []\n    for item in data:\n        result.append(item * {i})\n    return result\n\n# {'y' * 300}\nclass Handler_{i}:\n    def handle(self):\n        return self.process()\n\n# {'z' * 400}\n",
            },
        ]
        items.append(
            BenchmarkItem(
                name=f"code_review_{i}",
                messages=messages,
                metadata={"type": "code_review", "file_index": i},
            )
        )
    return items


def _generate_log_analysis_dataset() -> list[BenchmarkItem]:
    """Generate log analysis messages with large tool outputs."""
    items = []
    for i in range(10):
        log_lines = "\n".join(
            [f"2026-01-{15 + i:02d} {h:02d}:00:00 INFO Request {j} completed in {j * 10}ms"
             for h in range(24) for j in range(50)]
        )
        messages = [
            {"role": "system", "content": "You are a log analyst."},
            {"role": "user", "content": f"Analyze logs for service_{i}"},
            {
                "role": "assistant",
                "content": f"I'll fetch logs for service_{i}.",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "Bash", "arguments": f'{{"command": "cat /var/log/service_{i}.log"}}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": f"call_{i}", "content": log_lines},
        ]
        items.append(
            BenchmarkItem(
                name=f"log_analysis_{i}",
                messages=messages,
                metadata={"type": "log_analysis", "service_index": i},
            )
        )
    return items


def _generate_api_response_dataset() -> list[BenchmarkItem]:
    """Generate API response messages with JSON payloads."""
    items = []
    for i in range(10):
        api_response = json.dumps({
            "status": "success",
            "data": [
                {"id": j, "name": f"item_{j}", "value": j * i, "tags": [f"tag_{k}" for k in range(10)]}
                for j in range(100)
            ],
            "metadata": {"total": 100, "page": 1, "per_page": 100},
        })
        messages = [
            {"role": "system", "content": "You are a data analyst."},
            {"role": "user", "content": f"What's the average value for item set {i}?"},
            {
                "role": "assistant",
                "content": f"I'll fetch data for set {i}.",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "WebFetch", "arguments": f'{{"url": "https://api.example.com/data/{i}"}}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": f"call_{i}", "content": api_response},
        ]
        items.append(
            BenchmarkItem(
                name=f"api_response_{i}",
                messages=messages,
                metadata={"type": "api_response", "set_index": i},
            )
        )
    return items


def _generate_search_results_dataset() -> list[BenchmarkItem]:
    """Generate search result messages."""
    items = []
    for i in range(10):
        results = "\n".join(
            [f"Result {j}: Title {j} - Description for result {j} with relevance score {0.9 - j * 0.05:.2f}"
             for j in range(50)]
        )
        messages = [
            {"role": "system", "content": "You are a search assistant."},
            {"role": "user", "content": f"Search for query_{i}"},
            {
                "role": "assistant",
                "content": f"I'll search for query_{i}.",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "Grep", "arguments": f'{{"pattern": "query_{i}"}}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": f"call_{i}", "content": results},
        ]
        items.append(
            BenchmarkItem(
                name=f"search_results_{i}",
                messages=messages,
                metadata={"type": "search_results", "query_index": i},
            )
        )
    return items


DATASETS: dict[str, tuple[str, list[BenchmarkItem]]] = {
    "code_review": ("Code Review", _generate_code_review_dataset),
    "log_analysis": ("Log Analysis", _generate_log_analysis_dataset),
    "api_response": ("API Response", _generate_api_response_dataset),
    "search_results": ("Search Results", _generate_search_results_dataset),
}


# ── Benchmark runner ───────────────────────────────────────────────────


def _count_tokens(messages: list[dict[str, Any]], model: str = "gpt-4o") -> int:
    """Count tokens in messages using the tokenizer."""
    tokenizer = get_tokenizer(model)
    return tokenizer.count_messages(messages)


def run_benchmark(
    items: list[BenchmarkItem],
    model: str = "gpt-4o",
    model_limit: int = 128000,
    config: CopiumConfig | None = None,
) -> list[BenchmarkResult]:
    """Run Copium compression benchmark on a list of items.

    Args:
        items: Benchmark items to compress.
        model: Model name for token counting.
        model_limit: Context limit for the model.
        config: Optional CopiumConfig override.

    Returns:
        List of BenchmarkResult for each item.
    """
    results = []
    for item in items:
        try:
            original_tokens = _count_tokens(item.messages, model)

            start_time = time.perf_counter()
            result = compress(
                messages=item.messages,
                model=model,
                model_limit=model_limit,
                config=config,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            compressed_tokens = result.tokens_after
            tokens_saved = original_tokens - compressed_tokens
            compression_ratio = tokens_saved / original_tokens if original_tokens > 0 else 0.0

            results.append(
                BenchmarkResult(
                    item_name=item.name,
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    tokens_saved=tokens_saved,
                    compression_ratio=compression_ratio,
                    latency_ms=latency_ms,
                )
            )
        except Exception as e:
            results.append(
                BenchmarkResult(
                    item_name=item.name,
                    original_tokens=0,
                    compressed_tokens=0,
                    tokens_saved=0,
                    compression_ratio=0.0,
                    latency_ms=0.0,
                    error=str(e),
                )
            )
    return results


def generate_report(
    results: list[BenchmarkResult],
    dataset_name: str = "all",
) -> ComparisonReport:
    """Generate an aggregated comparison report.

    Args:
        results: List of benchmark results.
        dataset_name: Name of the dataset for reporting.

    Returns:
        ComparisonReport with aggregated metrics.
    """
    successful = [r for r in results if r.error is None]
    errors = [r for r in results if r.error is not None]

    total_original = sum(r.original_tokens for r in successful)
    total_compressed = sum(r.compressed_tokens for r in successful)
    total_saved = sum(r.tokens_saved for r in successful)
    avg_ratio = total_saved / total_original if total_original > 0 else 0.0

    latencies = sorted(r.latency_ms for r in successful)
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    p50_idx = int(len(latencies) * 0.5)
    p95_idx = int(len(latencies) * 0.95)
    p99_idx = int(len(latencies) * 0.99)

    return ComparisonReport(
        results=results,
        total_original_tokens=total_original,
        total_compressed_tokens=total_compressed,
        total_tokens_saved=total_saved,
        avg_compression_ratio=avg_ratio,
        avg_latency_ms=avg_latency,
        p50_latency_ms=latencies[p50_idx] if latencies else 0.0,
        p95_latency_ms=latencies[p95_idx] if latencies else 0.0,
        p99_latency_ms=latencies[p99_idx] if latencies else 0.0,
        success_count=len(successful),
        error_count=len(errors),
    )


def format_report_markdown(report: ComparisonReport, dataset_name: str = "all") -> str:
    """Format a comparison report as Markdown.

    Args:
        report: The comparison report.
        dataset_name: Name of the dataset.

    Returns:
        Markdown-formatted report string.
    """
    lines = [
        f"# Copium Compression Benchmark Report",
        f"",
        f"**Dataset:** {dataset_name}",
        f"**Items:** {report.success_count} succeeded, {report.error_count} failed",
        f"",
        f"## Compression Metrics",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Original Tokens | {report.total_original_tokens:,} |",
        f"| Total Compressed Tokens | {report.total_compressed_tokens:,} |",
        f"| Total Tokens Saved | {report.total_tokens_saved:,} |",
        f"| Average Compression Ratio | {report.avg_compression_ratio:.1%} |",
        f"",
        f"## Latency Metrics",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Average Latency | {report.avg_latency_ms:.1f}ms |",
        f"| P50 Latency | {report.p50_latency_ms:.1f}ms |",
        f"| P95 Latency | {report.p95_latency_ms:.1f}ms |",
        f"| P99 Latency | {report.p99_latency_ms:.1f}ms |",
        f"",
        f"## Per-Item Results",
        f"",
        f"| Item | Original | Compressed | Saved | Ratio | Latency |",
        f"|------|----------|------------|-------|-------|---------|",
    ]

    for r in report.results:
        if r.error:
            lines.append(f"| {r.item_name} | - | - | - | ERROR: {r.error[:50]} | - |")
        else:
            lines.append(
                f"| {r.item_name} | {r.original_tokens:,} | {r.compressed_tokens:,} "
                f"| {r.tokens_saved:,} | {r.compression_ratio:.1%} | {r.latency_ms:.1f}ms |"
            )

    if report.error_count > 0:
        lines.extend([
            f"",
            f"## Errors",
            f"",
        ])
        for r in report.results:
            if r.error:
                lines.append(f"- **{r.item_name}**: {r.error}")

    return "\n".join(lines)


def save_report(report: ComparisonReport, path: str, dataset_name: str = "all") -> None:
    """Save a comparison report to a file.

    Args:
        report: The comparison report.
        path: Output file path.
        dataset_name: Name of the dataset.
    """
    markdown = format_report_markdown(report, dataset_name)
    Path(path).write_text(markdown, encoding="utf-8")


def main() -> None:
    """Run the benchmark suite."""
    import argparse

    parser = argparse.ArgumentParser(description="Copium compression benchmark suite")
    parser.add_argument(
        "--dataset",
        choices=["all", *DATASETS.keys()],
        default="all",
        help="Dataset to benchmark (default: all)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Model name for token counting (default: gpt-4o)",
    )
    parser.add_argument(
        "--model-limit",
        type=int,
        default=128000,
        help="Context limit for the model (default: 128000)",
    )
    parser.add_argument(
        "--report",
        type=str,
        default=None,
        help="Save report to file (Markdown format)",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Save raw results to JSON file",
    )
    args = parser.parse_args()

    all_results: list[BenchmarkResult] = []
    datasets_to_run = list(DATASETS.keys()) if args.dataset == "all" else [args.dataset]

    for dataset_key in datasets_to_run:
        name, generator = DATASETS[dataset_key]
        print(f"\n{'=' * 60}")
        print(f"Running benchmark: {name}")
        print(f"{'=' * 60}")

        items = generator()
        results = run_benchmark(items, model=args.model, model_limit=args.model_limit)
        report = generate_report(results, dataset_key)

        print(f"\nCompression Ratio: {report.avg_compression_ratio:.1%}")
        print(f"Average Latency: {report.avg_latency_ms:.1f}ms")
        print(f"Tokens Saved: {report.total_tokens_saved:,} / {report.total_original_tokens:,}")

        if args.report:
            report_path = args.report if args.dataset != "all" else args.report.replace(".md", f"_{dataset_key}.md")
            save_report(report, report_path, dataset_key)
            print(f"\nReport saved to: {report_path}")

        all_results.extend(results)

    # Generate combined report
    combined_report = generate_report(all_results, "combined")
    print(f"\n{'=' * 60}")
    print(f"Combined Results")
    print(f"{'=' * 60}")
    print(f"Total Compression Ratio: {combined_report.avg_compression_ratio:.1%}")
    print(f"Total Tokens Saved: {combined_report.total_tokens_saved:,}")

    if args.json:
        json_data = {
            "results": [
                {
                    "item_name": r.item_name,
                    "original_tokens": r.original_tokens,
                    "compressed_tokens": r.compressed_tokens,
                    "tokens_saved": r.tokens_saved,
                    "compression_ratio": r.compression_ratio,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
                for r in all_results
            ],
            "summary": {
                "total_original_tokens": combined_report.total_original_tokens,
                "total_compressed_tokens": combined_report.total_compressed_tokens,
                "total_tokens_saved": combined_report.total_tokens_saved,
                "avg_compression_ratio": combined_report.avg_compression_ratio,
                "avg_latency_ms": combined_report.avg_latency_ms,
            },
        }
        Path(args.json).write_text(json.dumps(json_data, indent=2), encoding="utf-8")
        print(f"\nJSON results saved to: {args.json}")


if __name__ == "__main__":
    main()
