"""Quality benchmark runner for compression evaluation.

Measures ROUGE-L, IPS, and gate pass rates across content types
to validate that compression preserves answer quality.

Usage:
    python -m copium.quality.benchmark --dataset all
    python -m copium.quality.benchmark --dataset json --verbose
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from copium.quality.gate import ContentType, GateConfig, QualityGate
from copium.quality.metrics import QualityMetrics


def _default_compress(content: str) -> str:
    """Conservative default compressor used by benchmark examples."""
    words = content.split()
    if len(words) > 120:
        return " ".join(words[:90] + ["...", f"[{len(words) - 90} words compressed]"])
    return content


@dataclass
class BenchmarkSample:
    """A single benchmark sample."""

    content: str
    content_type: ContentType
    label: str = ""


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""

    dataset: str
    compressor: str
    rouge_l_mean: float
    ips_mean: float
    cwq_mean: float
    gate_pass_rate: float
    gate_revert_rate: float
    compression_ratio_mean: float
    token_savings_total: int
    n_samples: int
    latency_ms_mean: float
    benchmark_hash: str


@dataclass
class BenchmarkReport:
    """Full benchmark report across all datasets."""

    results: Dict[str, BenchmarkResult] = field(default_factory=dict)
    overall_rouge_l: float = 0.0
    overall_ips: float = 0.0
    overall_cwq: float = 0.0
    thresholds_met: Dict[str, bool] = field(default_factory=dict)
    timestamp: str = ""
    duration_seconds: float = 0.0


class QualityBenchmark:
    """Run quality benchmarks for compression evaluation.

    Validates that compression meets quality thresholds across
    content types: JSON, code, logs, search results, text.

    Example:
        benchmark = QualityBenchmark()
        benchmark.add_samples("json", json_samples)
        report = benchmark.run(compress_fn)
        assert report.thresholds_met["rouge_l_0.85"]
    """

    THRESHOLDS = {
        "rouge_l": 0.85,
        "ips": 0.95,
        "cwq": 0.85,
        "gate_pass_rate": 0.99,
    }

    def __init__(self, gate_config: Optional[GateConfig] = None):
        self._gate = QualityGate(gate_config)
        self._metrics = QualityMetrics()
        self._datasets: Dict[str, List[BenchmarkSample]] = {}

    def add_samples(self, dataset_name: str, samples: List[BenchmarkSample]) -> None:
        """Add benchmark samples for a dataset."""
        self._datasets[dataset_name] = samples

    def add_sample(self, dataset_name: str, content: str, content_type: ContentType, label: str = "") -> None:
        """Add a single sample to a dataset."""
        if dataset_name not in self._datasets:
            self._datasets[dataset_name] = []
        self._datasets[dataset_name].append(
            BenchmarkSample(content=content, content_type=content_type, label=label)
        )

    def run(
        self,
        compress_fn,
        compressor_name: str = "default",
        datasets: Optional[List[str]] = None,
    ) -> BenchmarkReport:
        """Run the benchmark suite.

        Args:
            compress_fn: Callable(str) -> str that compresses content.
            compressor_name: Name of the compressor being tested.
            datasets: Specific datasets to run (None = all).

        Returns:
            BenchmarkReport with all results.
        """
        start_time = time.time()
        report = BenchmarkReport(timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"))

        target_datasets = datasets or list(self._datasets.keys())

        all_rouge: List[float] = []
        all_ips: List[float] = []
        all_cwq: List[float] = []

        for dataset_name in target_datasets:
            samples = self._datasets.get(dataset_name, [])
            if not samples:
                continue

            result = self._run_dataset(dataset_name, samples, compress_fn, compressor_name)
            report.results[dataset_name] = result

            all_rouge.append(result.rouge_l_mean)
            all_ips.append(result.ips_mean)
            all_cwq.append(result.cwq_mean)

        if all_rouge:
            report.overall_rouge_l = sum(all_rouge) / len(all_rouge)
            report.overall_ips = sum(all_ips) / len(all_ips)
            report.overall_cwq = sum(all_cwq) / len(all_cwq)

        report.thresholds_met = {
            "rouge_l_0.85": report.overall_rouge_l >= self.THRESHOLDS["rouge_l"],
            "ips_0.95": report.overall_ips >= self.THRESHOLDS["ips"],
            "cwq_0.85": report.overall_cwq >= self.THRESHOLDS["cwq"],
        }

        report.duration_seconds = time.time() - start_time
        return report

    def _run_dataset(
        self,
        dataset_name: str,
        samples: List[BenchmarkSample],
        compress_fn,
        compressor_name: str,
    ) -> BenchmarkResult:
        """Run benchmark on a single dataset."""
        rouge_scores: List[float] = []
        ips_scores: List[float] = []
        cwq_scores: List[float] = []
        compression_ratios: List[float] = []
        token_savings_total = 0
        gate_passes = 0
        gate_reverts = 0
        latencies: List[float] = []

        for sample in samples:
            start = time.perf_counter()
            compressed = compress_fn(sample.content)
            compress_latency = (time.perf_counter() - start) * 1000

            # Quality gate check
            gate_result = self._gate.validate(
                sample.content, compressed, sample.content_type
            )

            if gate_result.passed:
                gate_passes += 1
                final_content = gate_result.compressed_content or compressed
            else:
                gate_reverts += 1
                final_content = gate_result.original_content or sample.content

            # Metrics
            metrics_result = self._metrics.compute(sample.content, final_content)
            rouge_scores.append(metrics_result.rouge_l)
            ips_scores.append(metrics_result.info_preservation_score)
            cwq_scores.append(metrics_result.compression_weighted_quality)
            compression_ratios.append(metrics_result.compression_ratio)
            token_savings_total += metrics_result.token_savings
            latencies.append(compress_latency)

        n = len(samples)
        total_checks = gate_passes + gate_reverts

        result_json = json.dumps({
            "dataset": dataset_name,
            "compressor": compressor_name,
            "n": n,
        }, sort_keys=True)
        benchmark_hash = hashlib.sha256(result_json.encode()).hexdigest()[:16]

        return BenchmarkResult(
            dataset=dataset_name,
            compressor=compressor_name,
            rouge_l_mean=sum(rouge_scores) / max(1, n),
            ips_mean=sum(ips_scores) / max(1, n),
            cwq_mean=sum(cwq_scores) / max(1, n),
            gate_pass_rate=gate_passes / max(1, total_checks),
            gate_revert_rate=gate_reverts / max(1, total_checks),
            compression_ratio_mean=sum(compression_ratios) / max(1, n),
            token_savings_total=token_savings_total,
            n_samples=n,
            latency_ms_mean=sum(latencies) / max(1, n),
            benchmark_hash=benchmark_hash,
        )

    def export_report(self, report: BenchmarkReport, output_dir: str) -> None:
        """Export benchmark report to JSON files."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Full results
        results_data = {}
        for name, result in report.results.items():
            results_data[name] = {
                "dataset": result.dataset,
                "compressor": result.compressor,
                "rouge_l_mean": result.rouge_l_mean,
                "ips_mean": result.ips_mean,
                "cwq_mean": result.cwq_mean,
                "gate_pass_rate": result.gate_pass_rate,
                "gate_revert_rate": result.gate_revert_rate,
                "compression_ratio_mean": result.compression_ratio_mean,
                "token_savings_total": result.token_savings_total,
                "n_samples": result.n_samples,
                "latency_ms_mean": result.latency_ms_mean,
                "benchmark_hash": result.benchmark_hash,
            }

        (output_path / "results.json").write_text(json.dumps(results_data, indent=2))

        # Summary
        summary = {
            "overall_rouge_l": report.overall_rouge_l,
            "overall_ips": report.overall_ips,
            "overall_cwq": report.overall_cwq,
            "thresholds_met": report.thresholds_met,
            "timestamp": report.timestamp,
            "duration_seconds": report.duration_seconds,
        }
        (output_path / "summary.json").write_text(json.dumps(summary, indent=2))


def generate_synthetic_samples() -> Dict[str, List[BenchmarkSample]]:
    """Generate synthetic benchmark samples for testing."""
    datasets: Dict[str, List[BenchmarkSample]] = {}

    # JSON samples
    json_samples = []
    for i in range(20):
        items = [{"id": f"item_{j}", "value": j * 10, "name": f"Item {j}"} for j in range(50)]
        content = json.dumps({"items": items, "total": 50, "page": i + 1})
        json_samples.append(BenchmarkSample(content=content, content_type=ContentType.JSON, label=f"json_{i}"))
    datasets["json"] = json_samples

    # Code samples
    code_samples = []
    for i in range(10):
        code = f"""import os
import sys
from pathlib import Path

class Handler{i}:
    def __init__(self, config):
        self.config = config
        self._cache = {{}}

    def process(self, data):
        result = self._transform(data)
        return result

    def _transform(self, data):
        return {{k: v * 2 for k, v in data.items()}}

def main():
    handler = Handler{i}({{"debug": True}})
    handler.process({{"x": 1, "y": 2}})

if __name__ == "__main__":
    main()
"""
        code_samples.append(BenchmarkSample(content=code, content_type=ContentType.CODE, label=f"code_{i}"))
    datasets["code"] = code_samples

    # Log samples
    log_samples = []
    for i in range(10):
        log = f"""[2026-06-22 10:00:{i:02d}] INFO: Starting process {i}
[2026-06-22 10:00:{i:02d}] DEBUG: Loading configuration
[2026-06-22 10:00:{i:02d}] INFO: Processing batch {i}
[2026-06-22 10:00:{i:02d}] WARNING: Slow query detected (>500ms)
[2026-06-22 10:00:{i:02d}] ERROR: Connection timeout to database
Traceback (most recent call last):
  File "app.py", line {100 + i}, in process
    result = db.query(sql)
  File "db.py", line 42, in query
    raise ConnectionError("timeout")
ConnectionError: timeout
[2026-06-22 10:00:{i:02d}] INFO: Retrying...
[2026-06-22 10:00:{i:02d}] INFO: Success after retry
"""
        log_samples.append(BenchmarkSample(content=log, content_type=ContentType.LOGS, label=f"log_{i}"))
    datasets["logs"] = log_samples

    return datasets
