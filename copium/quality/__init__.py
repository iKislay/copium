"""Quality preservation and validation for Copium compression.

Provides post-compression quality gates, metrics, and A/B testing
to ensure compression never silently degrades LLM answer quality.

Key components:
- QualityGate: Post-compression validation with auto-revert
- GateConfig: Configuration for quality thresholds
- ContentType: Content type classification for gate checks
- QualityMetrics: ROUGE-L, BERTScore, IPS, CWQ calculations
"""

from copium.quality.gate import ContentType, GateConfig, GateResult, QualityGate
from copium.quality.metrics import QualityMetrics

__all__ = [
    "ContentType",
    "GateConfig",
    "GateResult",
    "QualityGate",
    "QualityMetrics",
]
