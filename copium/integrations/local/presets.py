"""VRAM-constrained configuration presets.

Pre-built configurations for common local model setups that
minimize VRAM usage while maximizing compression effectiveness.
All compression runs on CPU — zero additional VRAM consumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VRAMConstrainedPreset:
    """A preset configuration for VRAM-constrained environments."""

    name: str
    description: str
    target_vram_gb: float
    compression_backend: str = "cpu_only"
    ml_compressor: bool = False
    transforms: list[str] = field(default_factory=list)
    ccr_storage: str = "memory"
    cache_aligner: bool = True
    smart_zone_pct: float = 0.4

    def to_proxy_config(self) -> dict[str, Any]:
        """Convert to proxy configuration dict."""
        return {
            "compression_backend": self.compression_backend,
            "ml_compressor": self.ml_compressor,
            "transforms": self.transforms,
            "ccr_storage": self.ccr_storage,
            "cache_aligner": self.cache_aligner,
            "smart_zone_pct": self.smart_zone_pct,
        }


# Pre-built presets for common GPU configurations
PRESET_8GB = VRAMConstrainedPreset(
    name="8gb",
    description="For 8GB GPUs (RTX 3060, RTX 4060, M1/M2 8GB)",
    target_vram_gb=8.0,
    transforms=[
        "SmartCrusher",
        "SessionDedup",
        "ErrorCompressor",
        "LogCompressor",
        "DiffCompressor",
        "SearchCompressor",
    ],
    ccr_storage="memory",
    smart_zone_pct=0.35,
)

PRESET_12GB = VRAMConstrainedPreset(
    name="12gb",
    description="For 12GB GPUs (RTX 3060 12GB, RTX 4070)",
    target_vram_gb=12.0,
    transforms=[
        "SmartCrusher",
        "SessionDedup",
        "ErrorCompressor",
        "LogCompressor",
        "DiffCompressor",
    ],
    ccr_storage="memory",
    smart_zone_pct=0.4,
)

PRESET_16GB = VRAMConstrainedPreset(
    name="16gb",
    description="For 16GB GPUs (RTX 4080, M1/M2 Pro 16GB)",
    target_vram_gb=16.0,
    transforms=[
        "SmartCrusher",
        "SessionDedup",
        "ErrorCompressor",
        "LogCompressor",
    ],
    ccr_storage="memory",
    smart_zone_pct=0.4,
)

PRESET_24GB = VRAMConstrainedPreset(
    name="24gb",
    description="For 24GB GPUs (RTX 3090, RTX 4090, M2 Max)",
    target_vram_gb=24.0,
    transforms=[
        "SmartCrusher",
        "SessionDedup",
    ],
    ccr_storage="memory",
    smart_zone_pct=0.45,
)

# All presets indexed by name
PRESETS: dict[str, VRAMConstrainedPreset] = {
    "8gb": PRESET_8GB,
    "12gb": PRESET_12GB,
    "16gb": PRESET_16GB,
    "24gb": PRESET_24GB,
}


def get_preset_for_vram(vram_mb: int) -> VRAMConstrainedPreset:
    """Select the best preset for a given VRAM amount.

    Args:
        vram_mb: Available VRAM in megabytes.

    Returns:
        The most appropriate preset for the hardware.
    """
    vram_gb = vram_mb / 1024

    if vram_gb <= 8:
        return PRESET_8GB
    elif vram_gb <= 12:
        return PRESET_12GB
    elif vram_gb <= 16:
        return PRESET_16GB
    else:
        return PRESET_24GB
