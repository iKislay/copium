"""KV cache precision-aware compression.

Local LLM users face a critical precision cliff: Q4_0 KV cache at 32K
context drops accuracy to 2.0% on AIME25 (vs 37.9% for FP16). This
module detects the KV cache precision and adjusts compression
aggressiveness accordingly.

Detection methods (tried in order):
1. Explicit config (user sets kv_cache_precision)
2. Environment variable (OLLAMA_KV_CACHE_TYPE, VLLM_KV_CACHE_DTYPE)
3. Backend /props or /health endpoints
4. Performance fingerprinting (latency-based heuristic)

Compression strategies by precision:
- FP16/BF16: Standard compression (baseline)
- Q8_0: Slightly more aggressive (10-20% more compression)
- Q4_0/Q4_K_M: Very aggressive (30-50% more compression), especially
  above 16K context where precision cliff begins
- Unknown: Conservative (assume worst case, aggressive compression)

The precision cliff for Q4_0:
- <16K tokens: ~90% of FP16 accuracy (mild degradation)
- 16K-32K tokens: ~50% of FP16 accuracy (significant degradation)
- >32K tokens: ~2% of FP16 accuracy (catastrophic degradation)
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class KVCachePrecision(Enum):
    """KV cache quantization precision levels."""

    FP32 = "fp32"
    FP16 = "fp16"
    BF16 = "bf16"
    Q8_0 = "q8_0"
    Q4_0 = "q4_0"
    Q4_K_M = "q4_k_m"
    Q4_K_S = "q4_k_s"
    Q5_0 = "q5_0"
    Q5_K_M = "q5_k_m"
    UNKNOWN = "unknown"


class CompressionStrategy(Enum):
    """Compression aggressiveness levels."""

    CONSERVATIVE = "conservative"  # Minimal compression (FP16/BF16)
    MODERATE = "moderate"  # Standard compression (Q8_0)
    AGGRESSIVE = "aggressive"  # Heavy compression (Q4_0+)
    ADAPTIVE = "adaptive"  # Scale with context length


@dataclass
class PrecisionProfile:
    """Characteristics of a KV cache precision level."""

    precision: KVCachePrecision
    bits_per_element: float  # Approximate bits per KV element
    accuracy_retention_32k: float  # Relative accuracy at 32K context
    recommended_strategy: CompressionStrategy
    context_thresholds: dict[str, int] = field(default_factory=dict)

    @property
    def is_low_precision(self) -> bool:
        return self.precision in (
            KVCachePrecision.Q4_0,
            KVCachePrecision.Q4_K_M,
            KVCachePrecision.Q4_K_S,
        )


# Precision profiles based on empirical measurements
PRECISION_PROFILES: dict[KVCachePrecision, PrecisionProfile] = {
    KVCachePrecision.FP32: PrecisionProfile(
        precision=KVCachePrecision.FP32,
        bits_per_element=32.0,
        accuracy_retention_32k=1.0,
        recommended_strategy=CompressionStrategy.CONSERVATIVE,
    ),
    KVCachePrecision.FP16: PrecisionProfile(
        precision=KVCachePrecision.FP16,
        bits_per_element=16.0,
        accuracy_retention_32k=0.95,
        recommended_strategy=CompressionStrategy.CONSERVATIVE,
    ),
    KVCachePrecision.BF16: PrecisionProfile(
        precision=KVCachePrecision.BF16,
        bits_per_element=16.0,
        accuracy_retention_32k=0.93,
        recommended_strategy=CompressionStrategy.CONSERVATIVE,
    ),
    KVCachePrecision.Q8_0: PrecisionProfile(
        precision=KVCachePrecision.Q8_0,
        bits_per_element=8.5,
        accuracy_retention_32k=0.85,
        recommended_strategy=CompressionStrategy.MODERATE,
    ),
    KVCachePrecision.Q4_0: PrecisionProfile(
        precision=KVCachePrecision.Q4_0,
        bits_per_element=4.5,
        accuracy_retention_32k=0.02,  # The precision cliff!
        recommended_strategy=CompressionStrategy.ADAPTIVE,
        context_thresholds={"safe": 8192, "degraded": 16384, "critical": 32768},
    ),
    KVCachePrecision.Q4_K_M: PrecisionProfile(
        precision=KVCachePrecision.Q4_K_M,
        bits_per_element=4.8,
        accuracy_retention_32k=0.15,
        recommended_strategy=CompressionStrategy.ADAPTIVE,
        context_thresholds={"safe": 8192, "degraded": 16384, "critical": 32768},
    ),
    KVCachePrecision.Q4_K_S: PrecisionProfile(
        precision=KVCachePrecision.Q4_K_S,
        bits_per_element=4.3,
        accuracy_retention_32k=0.10,
        recommended_strategy=CompressionStrategy.ADAPTIVE,
        context_thresholds={"safe": 8192, "degraded": 16384, "critical": 32768},
    ),
    KVCachePrecision.Q5_0: PrecisionProfile(
        precision=KVCachePrecision.Q5_0,
        bits_per_element=5.5,
        accuracy_retention_32k=0.70,
        recommended_strategy=CompressionStrategy.MODERATE,
    ),
    KVCachePrecision.Q5_K_M: PrecisionProfile(
        precision=KVCachePrecision.Q5_K_M,
        bits_per_element=5.8,
        accuracy_retention_32k=0.75,
        recommended_strategy=CompressionStrategy.MODERATE,
    ),
    KVCachePrecision.UNKNOWN: PrecisionProfile(
        precision=KVCachePrecision.UNKNOWN,
        bits_per_element=8.0,
        accuracy_retention_32k=0.5,
        recommended_strategy=CompressionStrategy.AGGRESSIVE,
    ),
}


def _detect_from_env() -> KVCachePrecision | None:
    """Detect KV cache precision from environment variables."""
    # Ollama
    kv_type = os.environ.get("OLLAMA_KV_CACHE_TYPE", "").lower()
    if kv_type:
        mapping = {
            "fp16": KVCachePrecision.FP16,
            "q8_0": KVCachePrecision.Q8_0,
            "q4_0": KVCachePrecision.Q4_0,
            "q4_k_m": KVCachePrecision.Q4_K_M,
            "q4_k_s": KVCachePrecision.Q4_K_S,
            "q5_0": KVCachePrecision.Q5_0,
            "q5_k_m": KVCachePrecision.Q5_K_M,
        }
        if kv_type in mapping:
            return mapping[kv_type]

    # VLLM
    vllm_dtype = os.environ.get("VLLM_KV_CACHE_DTYPE", "").lower()
    if vllm_dtype:
        if "fp16" in vllm_dtype:
            return KVCachePrecision.FP16
        if "fp8" in vllm_dtype or "e4m3" in vllm_dtype:
            return KVCachePrecision.Q8_0
        if "q8" in vllm_dtype:
            return KVCachePrecision.Q8_0
        if "q4" in vllm_dtype:
            return KVCachePrecision.Q4_0

    # llama.cpp
    llamacpp_kv = os.environ.get("LLAMA_CPP_KV_CACHE_TYPE", "").lower()
    if llamacpp_kv:
        mapping = {
            "f16": KVCachePrecision.FP16,
            "q8_0": KVCachePrecision.Q8_0,
            "q4_0": KVCachePrecision.Q4_0,
            "q4_1": KVCachePrecision.Q4_K_M,
        }
        if llamacpp_kv in mapping:
            return mapping[llamacpp_kv]

    return None


def _detect_from_endpoint(base_url: str, timeout: float = 2.0) -> KVCachePrecision | None:
    """Detect KV cache precision from backend API endpoints."""
    import urllib.request
    import json

    # Try Ollama /api/show
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/show",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"name": ""}).encode(),
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            kv_type = data.get("parameters", {}).get("num_gpu", "")
            # Check model details for quantization info
            details = data.get("details", {})
            quant = details.get("quantization_level", "").lower()
            if quant:
                return _parse_quantization_string(quant)
    except Exception:
        pass

    # Try Ollama /api/props
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/props")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            kv_type = data.get("kv_cache_type", "")
            if kv_type:
                return _parse_quantization_string(kv_type.lower())
    except Exception:
        pass

    # Try llama.cpp /props
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/props")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            kv_type = data.get("kv_cache_type", "")
            if kv_type:
                return _parse_quantization_string(kv_type.lower())
    except Exception:
        pass

    return None


def _parse_quantization_string(text: str) -> KVCachePrecision | None:
    """Parse a quantization string into a precision enum."""
    text = text.lower().strip()
    mapping = {
        "fp16": KVCachePrecision.FP16,
        "fp32": KVCachePrecision.FP32,
        "bf16": KVCachePrecision.BF16,
        "q8_0": KVCachePrecision.Q8_0,
        "q4_0": KVCachePrecision.Q4_0,
        "q4_k_m": KVCachePrecision.Q4_K_M,
        "q4_k_s": KVCachePrecision.Q4_K_S,
        "q5_0": KVCachePrecision.Q5_0,
        "q5_k_m": KVCachePrecision.Q5_K_M,
    }
    for key, precision in mapping.items():
        if key in text:
            return precision
    return None


def _fingerprint_precision(base_url: str, timeout: float = 5.0) -> KVCachePrecision | None:
    """Heuristic: send a small request and measure latency.

    Low-precision KV cache (Q4_0) is significantly faster than FP16
    for short contexts but degrades rapidly above the precision cliff.
    We use relative timing to guess.
    """
    import urllib.request
    import json

    try:
        # Send a minimal chat completion request
        payload = json.dumps({
            "model": "",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
        }).encode()

        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=payload,
        )

        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        elapsed = time.perf_counter() - start

        # Very rough heuristic: <200ms for a single token suggests
        # quantized KV, >500ms suggests full precision
        if elapsed < 0.2:
            return KVCachePrecision.Q4_0
        elif elapsed < 0.5:
            return KVCachePrecision.Q8_0
        else:
            return KVCachePrecision.FP16
    except Exception:
        return None


@dataclass
class KVCacheAwareConfig:
    """Configuration for KV cache-aware compression.

    Detects the KV cache precision and adjusts compression aggressiveness
    to avoid the precision cliff where quantized KV caches lose accuracy
    dramatically at high context lengths.

    The precision cliff for Q4_0 KV cache:
    - <16K tokens: ~90% of FP16 accuracy
    - 16K-32K tokens: ~50% of FP16 accuracy
    - >32K tokens: ~2% of FP16 accuracy (catastrophic)

    Detection methods:
    1. Explicit precision override
    2. Environment variable (OLLAMA_KV_CACHE_TYPE, VLLM_KV_CACHE_DTYPE)
    3. Backend API endpoint (/api/show, /props)
    4. Latency fingerprinting (fallback)
    """

    enabled: bool = True

    # Override: force a specific precision (disables auto-detection)
    precision_override: str | None = None

    # Backend URL for API-based detection
    backend_url: str | None = None

    # Whether to use latency fingerprinting as fallback
    use_fingerprinting: bool = False

    # Context length thresholds for adaptive compression
    # (used when precision is low and strategy is ADAPTIVE)
    context_safe_threshold: int = 8192
    context_degraded_threshold: int = 16384
    context_critical_threshold: int = 32768

    # Compression multiplier by strategy
    conservative_multiplier: float = 1.0  # Baseline
    moderate_multiplier: float = 1.2  # 20% more compression
    aggressive_multiplier: float = 1.5  # 50% more compression

    # Enable/disable detection methods
    detect_env: bool = True
    detect_endpoint: bool = True


class KVCacheDetector:
    """Detects KV cache precision from various sources."""

    def __init__(self, config: KVCacheAwareConfig):
        self.config = config
        self._cached_precision: KVCachePrecision | None = None
        self._detection_method: str = ""

    def detect(self) -> tuple[KVCachePrecision, str]:
        """Detect KV cache precision.

        Returns (precision, detection_method).
        """
        if self._cached_precision is not None:
            return self._cached_precision, self._detection_method

        # 1. Explicit override
        if self.config.precision_override:
            parsed = _parse_quantization_string(self.config.precision_override)
            if parsed:
                self._cached_precision = parsed
                self._detection_method = "explicit_override"
                return parsed, self._detection_method

        # 2. Environment variable
        if self.config.detect_env:
            env_precision = _detect_from_env()
            if env_precision:
                self._cached_precision = env_precision
                self._detection_method = "environment_variable"
                return env_precision, self._detection_method

        # 3. Backend endpoint
        if self.config.detect_endpoint and self.config.backend_url:
            endpoint_precision = _detect_from_endpoint(self.config.backend_url)
            if endpoint_precision:
                self._cached_precision = endpoint_precision
                self._detection_method = "backend_endpoint"
                return endpoint_precision, self._detection_method

        # 4. Fingerprinting
        if self.config.use_fingerprinting and self.config.backend_url:
            fp_precision = _fingerprint_precision(self.config.backend_url)
            if fp_precision:
                self._cached_precision = fp_precision
                self._detection_method = "latency_fingerprint"
                return fp_precision, self._detection_method

        # Default: unknown
        self._cached_precision = KVCachePrecision.UNKNOWN
        self._detection_method = "default_unknown"
        return KVCachePrecision.UNKNOWN, self._detection_method

    def reset(self) -> None:
        """Reset cached detection (for re-detection)."""
        self._cached_precision = None
        self._detection_method = ""


def get_compression_multiplier(
    precision: KVCachePrecision,
    context_tokens: int,
    config: KVCacheAwareConfig,
) -> float:
    """Get the compression aggressiveness multiplier.

    Returns a multiplier > 1.0 for more aggressive compression
    (fewer tokens kept), 1.0 for baseline.
    """
    profile = PRECISION_PROFILES.get(precision, PRECISION_PROFILES[KVCachePrecision.UNKNOWN])

    if profile.recommended_strategy == CompressionStrategy.CONSERVATIVE:
        return config.conservative_multiplier
    elif profile.recommended_strategy == CompressionStrategy.MODERATE:
        return config.moderate_multiplier
    elif profile.recommended_strategy == CompressionStrategy.AGGRESSIVE:
        return config.aggressive_multiplier
    elif profile.recommended_strategy == CompressionStrategy.ADAPTIVE:
        # Scale compression with context length relative to thresholds
        thresholds = profile.context_thresholds
        safe = thresholds.get("safe", config.context_safe_threshold)
        critical = thresholds.get("critical", config.context_critical_threshold)

        if context_tokens <= safe:
            # Below safe threshold: moderate compression
            return config.moderate_multiplier
        elif context_tokens >= critical:
            # Above critical threshold: maximum compression
            return config.aggressive_multiplier
        else:
            # In between: linear interpolation
            ratio = (context_tokens - safe) / (critical - safe)
            base = config.moderate_multiplier
            peak = config.aggressive_multiplier
            return base + ratio * (peak - base)

    return 1.0


def get_context_risk_level(
    precision: KVCachePrecision,
    context_tokens: int,
    config: KVCacheAwareConfig,
) -> str:
    """Get the risk level for the current context length and precision.

    Returns: 'safe', 'degraded', 'critical', 'catastrophic', or 'unknown'.
    """
    if precision == KVCachePrecision.UNKNOWN:
        return "unknown"

    profile = PRECISION_PROFILES.get(precision, PRECISION_PROFILES[KVCachePrecision.UNKNOWN])

    if not profile.is_low_precision:
        return "safe"

    thresholds = profile.context_thresholds
    safe = thresholds.get("safe", config.context_safe_threshold)
    degraded = thresholds.get("degraded", config.context_degraded_threshold)
    critical = thresholds.get("critical", config.context_critical_threshold)

    if context_tokens < safe:
        return "safe"
    elif context_tokens < degraded:
        return "degraded"
    elif context_tokens < critical:
        return "critical"
    else:
        return "catastrophic"
