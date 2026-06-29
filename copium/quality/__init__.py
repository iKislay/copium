"""Quality preservation and validation for Copium compression.

Provides post-compression quality gates, metrics, A/B testing, and
dashboards to ensure compression never silently degrades LLM answer quality.

Key components:
- QualityGate: Post-compression validation with auto-revert
- GateConfig: Configuration for quality thresholds
- ContentType: Content type classification for gate checks
- QualityMetrics: ROUGE-L, BERTScore, IPS, CWQ calculations
- ABTestHarness: A/B testing framework for compression experiments
- QualityDashboard: Real-time session quality monitoring
- QualityBenchmark: Benchmark runner for quality evaluation
"""

from copium.quality.ab_testing import ABTestConfig, ABTestHarness, ABTestResult
from copium.quality.benchmark import QualityBenchmark
from copium.quality.dashboard import QualityDashboard
from copium.quality.gate import ContentType, GateConfig, GateResult, QualityGate
from copium.quality.metrics import QualityMetrics

__all__ = [
    "ABTestConfig",
    "ABTestHarness",
    "ABTestResult",
    "ContentType",
    "GateConfig",
    "GateResult",
    "QualityBenchmark",
    "QualityDashboard",
    "QualityGate",
    "QualityMetrics",
]
