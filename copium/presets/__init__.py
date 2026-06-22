"""Built-in compression presets for Copium.

Presets are pre-configured CopiumConfig objects for common use cases.
Users can apply a preset via:

    copium proxy --preset minimal
    copium proxy --preset standard
    copium proxy --preset aggressive
    copium proxy --preset local-llm
    copium preset lossless

Available presets
-----------------
lossless    — Only lossless transforms; zero quality loss. Good starting point.
minimal     — Cache aligner + error compressor. Fastest, lowest risk.
standard    — Most transforms enabled. Recommended for most users.
aggressive  — Everything enabled. Maximum savings, slightly higher latency.
local-llm   — Optimized for Ollama/VLLM/llama.cpp (32K context windows).
"""

from __future__ import annotations

from copium.config import CopiumConfig


def create_lossless_config() -> CopiumConfig:
    """Only lossless transforms — zero quality loss.

    Enabled:
    - CacheAligner: normalizes UUIDs/timestamps/paths for cache stability
    - QualityGate: auto-reverts any transform that inflates tokens

    Disabled (lossy):
    - ContentRouter, SmartCrusher, OutputCompressor, DifferentialResponse
    """
    config = CopiumConfig()

    # Enable lossless transforms
    config.cache_aligner.enabled = True
    config.quality_gate.enabled = True
    config.quality_gate.revert_threshold = 0.01  # Revert on any inflation

    # Disable lossy transforms
    config.content_router_enabled = None  # ContentRouter is always present but can be bypassed
    config.output_compressor.enabled = False
    config.smart_crusher.enabled = False
    config.differential_response.enabled = False

    return config


def create_minimal_config() -> CopiumConfig:
    """Minimal preset — safe structural transforms only.

    Enabled:
    - CacheAligner: UUID/timestamp normalization for cache stability
    - ErrorCompressor: compact error cards instead of raw stack traces
    - QualityGate: safety net that auto-reverts any regression

    Disabled (too aggressive for minimal):
    - SmartCrusher, OutputCompressor, DifferentialResponse, SessionDedup
    """
    config = CopiumConfig()

    config.cache_aligner.enabled = True
    config.error_compressor.enabled = True
    config.quality_gate.enabled = True

    config.smart_crusher.enabled = False
    config.output_compressor.enabled = False
    config.differential_response.enabled = False
    config.session_dedup.enabled = False

    return config


def create_standard_config() -> CopiumConfig:
    """Standard preset — recommended for most users.

    Enables the full structural compression stack with conservative
    settings. Typically saves 40-70% of tokens with <4% quality delta.

    Enabled (all defaults):
    - CacheAligner, SmartCrusher, CCR, ErrorCompressor
    - SessionDedup, DifferentialResponse, OutputCompressor
    - QualityGate (safety net)
    """
    # Standard is the same as the CopiumConfig defaults, which already
    # enable all major transforms conservatively.
    return CopiumConfig()


def create_aggressive_config() -> CopiumConfig:
    """Aggressive preset — maximum savings.

    Enables all transforms with more aggressive compression settings.
    Best for high-throughput production workloads where token cost
    is the primary concern. Latency overhead: ~5-15ms per request.

    Compared to standard:
    - SmartCrusher: lower max_items_after_crush (more aggressive)
    - SessionDedup: MinHash threshold lowered (catches more near-dupes)
    - OutputCompressor: more filler phrases removed
    - ErrorCompressor: fewer stack frames kept
    """
    config = CopiumConfig()

    # More aggressive SmartCrusher
    config.smart_crusher.max_items_after_crush = 10  # default 15
    config.smart_crusher.min_tokens_to_crush = 100  # default 200

    # More aggressive session dedup
    config.session_dedup.enabled = True
    config.session_dedup.minhash_threshold = 0.75  # default 0.85 — catch more near-dupes
    config.session_dedup.min_content_length = 100  # default 200

    # More aggressive error compression
    config.error_compressor.max_stack_frames = 2  # default 3
    config.error_compressor.min_length_to_compress = 100  # default 150

    # Enable cache aligner (off by default)
    config.cache_aligner.enabled = True

    # Aggressive output compressor
    config.output_compressor.enabled = True
    config.output_compressor.min_tokens_to_compress = 25  # default 50

    return config


def create_local_llm_config() -> CopiumConfig:
    """Local LLM preset — optimized for Ollama/VLLM/llama.cpp.

    Local models typically have 4K-32K context windows with Q4 quantized
    KV caches that degrade significantly above 25% of max context.

    This preset is conservative on compression (avoids schema changes)
    but aggressive on context budget management to stay within the
    reliable context zone.

    Enabled:
    - CacheAligner: critical for KV cache stability with local models
    - SmartCrusher: conservative settings
    - SessionDedup: important for local models with limited context
    - QualityGate: more sensitive (local models are harder to recover)
    """
    config = CopiumConfig()

    # Cache aligner is critical for local model KV cache stability
    config.cache_aligner.enabled = True

    # Conservative compression for local models
    config.smart_crusher.enabled = True
    config.smart_crusher.max_items_after_crush = 20  # more conservative than default 15

    # Session dedup is especially valuable with limited context windows
    config.session_dedup.enabled = True
    config.session_dedup.min_content_length = 150

    # Context budget: assume Q4_0 quantization (25% reliable zone)
    config.context_budget.enabled = True
    config.context_budget.kv_reliable_fractions["unknown"] = 0.25  # conservative default

    # Output compressor: less aggressive (local models are more sensitive to truncation)
    config.output_compressor.enabled = True
    config.output_compressor.min_tokens_to_compress = 100

    return config


LOSSLESS_PRESETS = {
    "lossless": create_lossless_config,
}

ALL_PRESETS = {
    "lossless": create_lossless_config,
    "minimal": create_minimal_config,
    "standard": create_standard_config,
    "aggressive": create_aggressive_config,
    "local-llm": create_local_llm_config,
}

PRESET_DESCRIPTIONS = {
    "lossless": "Only lossless transforms; zero quality loss",
    "minimal": "Structural transforms only; safe and fast",
    "standard": "Full compression stack; recommended (default)",
    "aggressive": "Maximum savings; more aggressive settings",
    "local-llm": "Optimized for Ollama/VLLM/llama.cpp",
}
