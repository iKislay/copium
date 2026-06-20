"""KV cache-aware compression transform for the pipeline.

Detects the backend's KV cache precision and adjusts compression
aggressiveness to avoid the precision cliff. This transform doesn't
compress content itself — it sets context variables that other
transforms (ContentRouter, OutputCompressor) use to scale their
aggressiveness.
"""

from __future__ import annotations

from typing import Any

from ..config import TransformResult
from ..kv_aware import (
    KVCacheAwareConfig,
    KVCacheDetector,
    KVCachePrecision,
    PRECISION_PROFILES,
    get_compression_multiplier,
    get_context_risk_level,
)
from ..tokenizer import Tokenizer
from .base import Transform


class KVCacheAwareTransform(Transform):
    """Detects KV cache precision and provides compression scaling info.

    This transform annotates the pipeline context with:
    - kv_cache_precision: Detected precision level
    - kv_cache_multiplier: Compression aggressiveness multiplier
    - kv_cache_risk: Context risk level (safe/degraded/critical/catastrophic)

    After apply(), call get_annotations() to get the detected values
    for passing to downstream transforms.
    """

    name = "kv_cache_aware"

    def __init__(self, config: KVCacheAwareConfig | None = None):
        self.config = config or KVCacheAwareConfig()
        self.detector = KVCacheDetector(self.config)
        # Detected values stored here for pipeline to retrieve
        self.precision: str = ""
        self.multiplier: float = 1.0
        self.risk: str = ""
        self.detection_method: str = ""

    def get_annotations(self) -> dict[str, Any]:
        """Get the detected KV cache annotations for downstream transforms."""
        return {
            "kv_cache_precision": self.precision,
            "kv_cache_multiplier": self.multiplier,
            "kv_cache_risk": self.risk,
            "kv_cache_detection_method": self.detection_method,
        }

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Detect KV cache precision and annotate pipeline context.

        This transform doesn't modify messages. It detects the KV cache
        precision and provides scaling information that other transforms
        can use.
        """
        if not self.config.enabled:
            return TransformResult(
                messages=messages,
                tokens_before=tokenizer.count_messages(messages),
                tokens_after=tokenizer.count_messages(messages),
                transforms_applied=[],
            )

        tokens_before = tokenizer.count_messages(messages)

        # Detect precision
        precision_enum, method = self.detector.detect()

        # Get current context length
        context_tokens = tokens_before

        # Calculate compression multiplier
        multiplier = get_compression_multiplier(precision_enum, context_tokens, self.config)

        # Get risk level
        risk = get_context_risk_level(precision_enum, context_tokens, self.config)

        # Store on instance for pipeline to retrieve
        self.precision = precision_enum.value
        self.multiplier = multiplier
        self.risk = risk
        self.detection_method = method

        # Log if precision is low and context is significant
        profile = PRECISION_PROFILES.get(precision_enum, PRECISION_PROFILES[KVCachePrecision.UNKNOWN])
        if profile.is_low_precision and context_tokens > 8192:
            import logging

            logger = logging.getLogger(__name__)
            logger.info(
                "KV cache precision detected: %s (method=%s, context=%d tokens, "
                "risk=%s, compression_multiplier=%.2f)",
                precision_enum.value,
                method,
                context_tokens,
                risk,
                multiplier,
            )

        return TransformResult(
            messages=messages,
            tokens_before=tokens_before,
            tokens_after=tokens_before,  # No transformation
            transforms_applied=[
                f"kv_cache:{precision_enum.value}:{method}"
                if precision_enum != KVCachePrecision.UNKNOWN
                else "kv_cache:unknown"
            ],
        )
