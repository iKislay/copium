"""Evaluation runners for different scenarios."""

from copium.evals.runners.before_after import BeforeAfterRunner
from copium.evals.runners.compression_only import CompressionOnlyRunner

__all__ = ["BeforeAfterRunner", "CompressionOnlyRunner"]
