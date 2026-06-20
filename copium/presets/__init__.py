"""Lossless-Only Mode.

A compression mode that only applies lossless transforms.
Risk-averse users can start here with zero quality loss.
"""

from __future__ import annotations

from copium.config import CopiumConfig


def create_lossless_config() -> CopiumConfig:
    """Create a CopiumConfig with only lossless transforms enabled.

    Lossless transforms:
    - CacheAligner: Aligns cache breakpoints (no content change)
    - QualityGate: Auto-revert on any inflation (safety)

    NOT included (lossy):
    - ContentRouter: May drop content
    - OutputCompressor: Removes filler phrases
    - SmartCrusher: Statistical compression
    - DifferentialResponse: May lose context
    - TOONEncoder: Changes format (though lossless)
    """
    config = CopiumConfig()

    # Enable lossless transforms
    config.cache_aligner.enabled = True
    config.quality_gate.enabled = True
    config.quality_gate.revert_threshold = 0.01  # Revert on any inflation

    # Disable lossy transforms
    config.content_router.enabled = False
    config.output_compressor.enabled = False
    config.smart_crusher.enabled = False
    config.differential_response.enabled = False

    return config


LOSSLESS_PRESETS = {
    "lossless": create_lossless_config,
}
