"""Tests for agent_context compression scheduler."""

from copium.agent_context.compression_scheduler import (
    CompressionPlan,
    CompressionScheduler,
    TransformSpec,
)
from copium.agent_context.phase_detector import AgentPhase
from copium.agent_context.smart_zone import CompressionLevel
from copium.agent_context.tool_call_classifier import (
    ClassifiedToolCall,
    ToolCallClassifier,
    ToolCallType,
)


class TestCompressionScheduler:
    """Test compression scheduling."""

    def setup_method(self):
        self.scheduler = CompressionScheduler()
        self.classifier = ToolCallClassifier()

    def test_schedule_orientation_phase(self):
        classified = self.classifier.classify("list_dir", {"path": "/"})
        plan = self.scheduler.schedule(
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.LOSSLESS,
            classified=classified,
        )
        assert plan.phase == AgentPhase.ORIENTATION
        assert len(plan.transforms) > 0
        transform_names = [t.name for t in plan.transforms]
        assert "smart_crusher" in transform_names

    def test_schedule_implementation_phase(self):
        classified = self.classifier.classify("write_file", {"path": "x.py"})
        plan = self.scheduler.schedule(
            phase=AgentPhase.IMPLEMENTATION,
            compression_level=CompressionLevel.LIGHT_LOSSY,
            classified=classified,
        )
        assert plan.phase == AgentPhase.IMPLEMENTATION
        # Implementation preserves code — less aggressive
        assert plan.target_reduction < 0.5

    def test_schedule_verification_includes_diff(self):
        classified = self.classifier.classify("run_tests")
        plan = self.scheduler.schedule(
            phase=AgentPhase.VERIFICATION,
            compression_level=CompressionLevel.MODERATE_LOSSY,
            classified=classified,
        )
        transform_names = [t.name for t in plan.transforms]
        assert "differential_response" in transform_names

    def test_aggressive_level_adds_more_transforms(self):
        classified = self.classifier.classify("list_dir")
        plan = self.scheduler.schedule(
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.AGGRESSIVE_LOSSY,
            classified=classified,
        )
        # Should have output_compressor at aggressive level
        transform_names = [t.name for t in plan.transforms]
        assert "output_compressor" in transform_names

    def test_schedule_batch_sorted_by_priority(self):
        classified_calls = [
            self.classifier.classify("read_file", {"path": "x.py"}),
            self.classifier.classify("list_dir", {"path": "/"}),
            self.classifier.classify("grep_search", {"query": "foo"}),
        ]
        plans = self.scheduler.schedule_batch(
            phase=AgentPhase.EXPLORATION,
            compression_level=CompressionLevel.LOSSLESS,
            classified_calls=classified_calls,
        )
        assert len(plans) == 3
        # Plans should be sorted by priority (highest first)
        assert plans[0].priority >= plans[1].priority >= plans[2].priority

    def test_target_reduction_scales_with_compressibility(self):
        # Highly compressible content
        dir_classified = self.classifier.classify("list_dir")
        dir_plan = self.scheduler.schedule(
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.MODERATE_LOSSY,
            classified=dir_classified,
        )
        # Low compressibility content
        file_classified = self.classifier.classify("read_file", {"path": "x.py"})
        file_plan = self.scheduler.schedule(
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.MODERATE_LOSSY,
            classified=file_classified,
        )
        assert dir_plan.target_reduction > file_plan.target_reduction

    def test_context_pressure_increases_priority(self):
        classified = self.classifier.classify("list_dir")
        low_pressure = self.scheduler.schedule(
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.LOSSLESS,
            classified=classified,
            context_pressure=0.2,
        )
        high_pressure = self.scheduler.schedule(
            phase=AgentPhase.ORIENTATION,
            compression_level=CompressionLevel.LOSSLESS,
            classified=classified,
            context_pressure=0.9,
        )
        assert high_pressure.priority > low_pressure.priority
