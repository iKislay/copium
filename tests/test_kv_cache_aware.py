"""Tests for KV cache-aware compression."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from copium.kv_aware import (
    KVCacheAwareConfig,
    KVCacheDetector,
    KVCachePrecision,
    PRECISION_PROFILES,
    CompressionStrategy,
    _detect_from_env,
    _parse_quantization_string,
    get_compression_multiplier,
    get_context_risk_level,
)
from copium.transforms.kv_cache_aware import KVCacheAwareTransform


class TestPrecisionProfiles:
    """Test precision profile definitions."""

    def test_all_profiles_exist(self):
        for precision in KVCachePrecision:
            assert precision in PRECISION_PROFILES

    def test_fp16_is_high_precision(self):
        profile = PRECISION_PROFILES[KVCachePrecision.FP16]
        assert not profile.is_low_precision
        assert profile.accuracy_retention_32k > 0.9
        assert profile.recommended_strategy == CompressionStrategy.CONSERVATIVE

    def test_q4_0_is_low_precision(self):
        profile = PRECISION_PROFILES[KVCachePrecision.Q4_0]
        assert profile.is_low_precision
        assert profile.accuracy_retention_32k < 0.1  # The precision cliff!
        assert profile.recommended_strategy == CompressionStrategy.ADAPTIVE

    def test_q8_0_moderate(self):
        profile = PRECISION_PROFILES[KVCachePrecision.Q8_0]
        assert not profile.is_low_precision
        assert profile.recommended_strategy == CompressionStrategy.MODERATE


class TestParseQuantizationString:
    """Test quantization string parsing."""

    def test_known_types(self):
        assert _parse_quantization_string("fp16") == KVCachePrecision.FP16
        assert _parse_quantization_string("q8_0") == KVCachePrecision.Q8_0
        assert _parse_quantization_string("q4_0") == KVCachePrecision.Q4_0
        assert _parse_quantization_string("q4_k_m") == KVCachePrecision.Q4_K_M

    def test_case_insensitive(self):
        assert _parse_quantization_string("FP16") == KVCachePrecision.FP16
        assert _parse_quantization_string("Q4_0") == KVCachePrecision.Q4_0

    def test_unknown_type(self):
        assert _parse_quantization_string("unknown_type") is None
        assert _parse_quantization_string("") is None

    def test_partial_match(self):
        assert _parse_quantization_string("using q4_0 for kv") == KVCachePrecision.Q4_0


class TestDetectFromEnv:
    """Test environment variable detection."""

    def test_ollama_kv_cache_type(self):
        with patch.dict(os.environ, {"OLLAMA_KV_CACHE_TYPE": "q4_0"}):
            assert _detect_from_env() == KVCachePrecision.Q4_0

    def test_vllm_kv_cache_dtype(self):
        with patch.dict(os.environ, {"VLLM_KV_CACHE_DTYPE": "fp8_e4m3"}):
            assert _detect_from_env() == KVCachePrecision.Q8_0

    def test_llamacpp_kv_cache_type(self):
        with patch.dict(os.environ, {"LLAMA_CPP_KV_CACHE_TYPE": "q8_0"}):
            assert _detect_from_env() == KVCachePrecision.Q8_0

    def test_no_env_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _detect_from_env() is None

    def test_ollama_fp16(self):
        with patch.dict(os.environ, {"OLLAMA_KV_CACHE_TYPE": "fp16"}):
            assert _detect_from_env() == KVCachePrecision.FP16


class TestCompressionMultiplier:
    """Test compression multiplier calculation."""

    def test_fp16_baseline(self):
        config = KVCacheAwareConfig()
        multiplier = get_compression_multiplier(KVCachePrecision.FP16, 10000, config)
        assert multiplier == 1.0

    def test_q8_0_moderate(self):
        config = KVCacheAwareConfig()
        multiplier = get_compression_multiplier(KVCachePrecision.Q8_0, 10000, config)
        assert multiplier == 1.2

    def test_q4_0_adaptive_safe(self):
        config = KVCacheAwareConfig()
        multiplier = get_compression_multiplier(KVCachePrecision.Q4_0, 4096, config)
        assert multiplier == 1.2  # Below safe threshold → moderate

    def test_q4_0_adaptive_critical(self):
        config = KVCacheAwareConfig()
        multiplier = get_compression_multiplier(KVCachePrecision.Q4_0, 40000, config)
        assert multiplier == 1.5  # Above critical threshold → aggressive

    def test_q4_0_adaptive_interpolation(self):
        config = KVCacheAwareConfig()
        # Midpoint between safe (8192) and critical (32768) = 20480
        multiplier = get_compression_multiplier(KVCachePrecision.Q4_0, 20480, config)
        # Should be between moderate (1.2) and aggressive (1.5)
        assert 1.2 < multiplier < 1.5

    def test_custom_multipliers(self):
        config = KVCacheAwareConfig(
            conservative_multiplier=1.0,
            moderate_multiplier=1.3,
            aggressive_multiplier=2.0,
        )
        assert get_compression_multiplier(KVCachePrecision.Q8_0, 10000, config) == 1.3
        assert get_compression_multiplier(KVCachePrecision.Q4_0, 50000, config) == 2.0


class TestContextRiskLevel:
    """Test context risk level assessment."""

    def test_fp16_always_safe(self):
        config = KVCacheAwareConfig()
        assert get_context_risk_level(KVCachePrecision.FP16, 100000, config) == "safe"

    def test_q4_0_safe(self):
        config = KVCacheAwareConfig()
        assert get_context_risk_level(KVCachePrecision.Q4_0, 4096, config) == "safe"

    def test_q4_0_degraded(self):
        config = KVCacheAwareConfig()
        assert get_context_risk_level(KVCachePrecision.Q4_0, 12000, config) == "degraded"

    def test_q4_0_critical(self):
        config = KVCacheAwareConfig()
        assert get_context_risk_level(KVCachePrecision.Q4_0, 24000, config) == "critical"

    def test_q4_0_catastrophic(self):
        config = KVCacheAwareConfig()
        assert get_context_risk_level(KVCachePrecision.Q4_0, 40000, config) == "catastrophic"

    def test_unknown_precision_safe(self):
        config = KVCacheAwareConfig()
        assert get_context_risk_level(KVCachePrecision.UNKNOWN, 100000, config) == "unknown"


class TestKVCacheDetector:
    """Test the KV cache detector."""

    def test_explicit_override(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        detector = KVCacheDetector(config)
        precision, method = detector.detect()
        assert precision == KVCachePrecision.Q4_0
        assert method == "explicit_override"

    def test_explicit_override_case_insensitive(self):
        config = KVCacheAwareConfig(precision_override="FP16")
        detector = KVCacheDetector(config)
        precision, _ = detector.detect()
        assert precision == KVCachePrecision.FP16

    def test_env_detection(self):
        config = KVCacheAwareConfig()
        detector = KVCacheDetector(config)
        with patch.dict(os.environ, {"OLLAMA_KV_CACHE_TYPE": "q8_0"}):
            precision, method = detector.detect()
            assert precision == KVCachePrecision.Q8_0
            assert method == "environment_variable"

    def test_detection_caches_result(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        detector = KVCacheDetector(config)
        p1, m1 = detector.detect()
        p2, m2 = detector.detect()
        assert p1 == p2
        assert m1 == m2

    def test_reset(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        detector = KVCacheDetector(config)
        detector.detect()
        detector.reset()
        # Should re-detect
        config.precision_override = "fp16"
        precision, _ = detector.detect()
        assert precision == KVCachePrecision.FP16

    def test_unknown_precision(self):
        config = KVCacheAwareConfig(detect_env=False, detect_endpoint=False)
        detector = KVCacheDetector(config)
        precision, method = detector.detect()
        assert precision == KVCachePrecision.UNKNOWN
        assert method == "default_unknown"


class TestKVCacheAwareTransform:
    """Test the KV cache-aware transform."""

    def _make_messages(self):
        return [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

    def _run_transform(self, config=None, env_vars=None):
        from copium.tokenizers import get_tokenizer
        from copium.tokenizer import Tokenizer

        tc = get_tokenizer("gpt-4")
        tokenizer = Tokenizer(tc, "gpt-4")
        kv_config = config or KVCacheAwareConfig()
        transform = KVCacheAwareTransform(kv_config)

        messages = self._make_messages()

        if env_vars:
            with patch.dict(os.environ, env_vars):
                result = transform.apply(messages, tokenizer)
        else:
            result = transform.apply(messages, tokenizer)

        annotations = transform.get_annotations()
        return result, annotations

    def test_sets_precision_in_annotations(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        result, annotations = self._run_transform(config)
        assert annotations["kv_cache_precision"] == "q4_0"

    def test_sets_multiplier_in_annotations(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        result, annotations = self._run_transform(config)
        assert "kv_cache_multiplier" in annotations
        assert isinstance(annotations["kv_cache_multiplier"], float)

    def test_sets_risk_in_annotations(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        result, annotations = self._run_transform(config)
        assert "kv_cache_risk" in annotations

    def test_disabled_config(self):
        config = KVCacheAwareConfig(enabled=False)
        result, annotations = self._run_transform(config)
        assert annotations.get("kv_cache_precision", "") == ""
        assert result.transforms_applied == []

    def test_messages_unchanged(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        result, _ = self._run_transform(config)
        assert result.messages == self._make_messages()

    def test_tokens_unchanged(self):
        config = KVCacheAwareConfig(precision_override="q4_0")
        result, _ = self._run_transform(config)
        assert result.tokens_before == result.tokens_after

    def test_transform_applied_recorded(self):
        config = KVCacheAwareConfig(precision_override="q8_0")
        result, _ = self._run_transform(config)
        assert any("kv_cache:" in t for t in result.transforms_applied)

    def test_env_detection_integration(self):
        config = KVCacheAwareConfig()
        result, annotations = self._run_transform(
            config, env_vars={"OLLAMA_KV_CACHE_TYPE": "q4_0"}
        )
        assert annotations["kv_cache_precision"] == "q4_0"
        assert annotations["kv_cache_detection_method"] == "environment_variable"
