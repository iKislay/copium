"""VRAM monitoring for local model environments.

Provides GPU memory usage detection for NVIDIA (nvidia-smi),
AMD (rocm-smi), and Apple Silicon (Metal) GPUs. Used by the
adaptive compression engine to scale aggressiveness based on
available memory.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VRAMStatus:
    """Current VRAM status for a GPU."""

    device_id: int = 0
    device_name: str = "unknown"
    total_mb: int = 0
    used_mb: int = 0
    free_mb: int = 0

    @property
    def utilization(self) -> float:
        """VRAM utilization as a fraction (0.0-1.0)."""
        if self.total_mb == 0:
            return 0.0
        return self.used_mb / self.total_mb

    @property
    def free_fraction(self) -> float:
        """Free VRAM as a fraction (0.0-1.0)."""
        return 1.0 - self.utilization


class VRAMMonitor:
    """Monitor GPU VRAM usage across different hardware.

    Supports:
    - NVIDIA GPUs via nvidia-smi
    - AMD GPUs via rocm-smi
    - Apple Silicon via system_profiler (unified memory)

    Usage:
        monitor = VRAMMonitor()
        status = monitor.get_status()
        if status.free_fraction < 0.2:
            # Low VRAM — use aggressive compression
            ...
    """

    def __init__(self) -> None:
        self._backend = self._detect_backend()

    def get_status(self, device_id: int = 0) -> VRAMStatus:
        """Get current VRAM status for the specified device."""
        if self._backend == "nvidia":
            return self._nvidia_status(device_id)
        elif self._backend == "amd":
            return self._amd_status(device_id)
        elif self._backend == "apple":
            return self._apple_status()
        else:
            return VRAMStatus()

    def get_all_devices(self) -> list[VRAMStatus]:
        """Get VRAM status for all detected GPUs."""
        if self._backend == "nvidia":
            return self._nvidia_all_devices()
        elif self._backend == "amd":
            return self._amd_all_devices()
        elif self._backend == "apple":
            return [self._apple_status()]
        return []

    def get_free_vram_mb(self, device_id: int = 0) -> int:
        """Get free VRAM in MB."""
        return self.get_status(device_id).free_mb

    def get_total_vram_mb(self, device_id: int = 0) -> int:
        """Get total VRAM in MB."""
        return self.get_status(device_id).total_mb

    def _detect_backend(self) -> str:
        """Detect available GPU monitoring backend."""
        if platform.system() == "Darwin":
            return "apple"

        # Check for nvidia-smi
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return "nvidia"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Check for rocm-smi
        try:
            result = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return "amd"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return "none"

    def _nvidia_status(self, device_id: int = 0) -> VRAMStatus:
        """Get VRAM status from nvidia-smi."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--id={device_id}",
                    "--query-gpu=name,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return VRAMStatus(device_id=device_id)

            line = result.stdout.strip()
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                return VRAMStatus(
                    device_id=device_id,
                    device_name=parts[0],
                    total_mb=int(parts[1]),
                    used_mb=int(parts[2]),
                    free_mb=int(parts[3]),
                )
        except (subprocess.TimeoutExpired, ValueError, IndexError):
            pass
        return VRAMStatus(device_id=device_id)

    def _nvidia_all_devices(self) -> list[VRAMStatus]:
        """Get VRAM status for all NVIDIA GPUs."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return []

            devices = []
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    devices.append(
                        VRAMStatus(
                            device_id=int(parts[0]),
                            device_name=parts[1],
                            total_mb=int(parts[2]),
                            used_mb=int(parts[3]),
                            free_mb=int(parts[4]),
                        )
                    )
            return devices
        except (subprocess.TimeoutExpired, ValueError):
            return []

    def _amd_status(self, device_id: int = 0) -> VRAMStatus:
        """Get VRAM status from rocm-smi."""
        try:
            result = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram", "--json"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return VRAMStatus(device_id=device_id)

            import json

            data = json.loads(result.stdout)
            # rocm-smi JSON format varies by version
            device_key = f"card{device_id}"
            if device_key in data:
                dev = data[device_key]
                total = int(dev.get("VRAM Total Memory (B)", 0)) // (1024 * 1024)
                used = int(dev.get("VRAM Total Used Memory (B)", 0)) // (1024 * 1024)
                return VRAMStatus(
                    device_id=device_id,
                    device_name=f"AMD GPU {device_id}",
                    total_mb=total,
                    used_mb=used,
                    free_mb=total - used,
                )
        except (subprocess.TimeoutExpired, ValueError, KeyError):
            pass
        return VRAMStatus(device_id=device_id)

    def _amd_all_devices(self) -> list[VRAMStatus]:
        """Get VRAM status for all AMD GPUs."""
        devices = []
        for i in range(8):  # Check up to 8 devices
            status = self._amd_status(i)
            if status.total_mb > 0:
                devices.append(status)
            else:
                break
        return devices

    def _apple_status(self) -> VRAMStatus:
        """Get unified memory status for Apple Silicon.

        Apple Silicon uses unified memory shared between CPU and GPU.
        We report total system memory as an approximation.
        """
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                total_bytes = int(result.stdout.strip())
                total_mb = total_bytes // (1024 * 1024)
                # Estimate GPU-available as ~75% of unified memory
                gpu_total = int(total_mb * 0.75)

                # Try to get memory pressure
                used_mb = self._apple_memory_pressure(total_mb)

                return VRAMStatus(
                    device_id=0,
                    device_name="Apple Silicon (Unified)",
                    total_mb=gpu_total,
                    used_mb=used_mb,
                    free_mb=gpu_total - used_mb,
                )
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return VRAMStatus(device_name="Apple Silicon (Unified)")

    def _apple_memory_pressure(self, total_mb: int) -> int:
        """Estimate memory usage on macOS."""
        try:
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Parse vm_stat output for active + wired pages
                active = 0
                wired = 0
                for line in result.stdout.split("\n"):
                    if "Pages active:" in line:
                        active = int(line.split(":")[1].strip().rstrip("."))
                    elif "Pages wired" in line:
                        wired = int(line.split(":")[1].strip().rstrip("."))
                # Pages are 4096 bytes each
                used_bytes = (active + wired) * 4096
                return used_bytes // (1024 * 1024)
        except (subprocess.TimeoutExpired, ValueError):
            pass
        # Default: assume 60% utilization
        return int(total_mb * 0.6)
