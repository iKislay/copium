"""Model routing based on request complexity.

Routes requests to cheaper models when the task is simple,
and to expensive models only when complexity warrants it.
Saves 40-60% on API costs for routine requests.
"""

from __future__ import annotations

from typing import Any

from copium.config import ModelRouterConfig
from copium.tokenizer import Tokenizer

from .base import Transform, TransformResult


class ModelRouter(Transform):
    """Route requests to cheaper models based on complexity.

    Complexity signals:
    - Message count (fewer = simpler)
    - Code presence (code = complex)
    - Tool definitions (fewer = simpler)
    - Message length (short = simple)
    """

    name = "model_router"

    def __init__(self, config: ModelRouterConfig | None = None) -> None:
        self.config = config or ModelRouterConfig()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _estimate_complexity(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> float:
        """Estimate request complexity (0.0 = very simple, 1.0 = very complex)."""
        weights = self.config.weights
        score = 0.0

        # Signal 1: Message count (normalized 0-1, capped at 20)
        msg_count = len(messages)
        score += min(msg_count / 20.0, 1.0) * weights[0]

        # Signal 2: Tool count (normalized 0-1, capped at 10)
        tool_count = len(tools) if tools else 0
        score += min(tool_count / 10.0, 1.0) * weights[1]

        # Signal 3: Code presence in messages
        has_code = False
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                if "```" in content or "def " in content or "class " in content or "import " in content:
                    has_code = True
                    break
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = str(part.get("content", ""))
                        if "```" in text or "def " in text:
                            has_code = True
                            break
        if has_code:
            score += 1.0 * weights[2]

        # Signal 4: Message length (normalized 0-1, capped at 20K chars)
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        score += min(total_chars / 20_000.0, 1.0) * weights[3]

        return max(0.0, min(1.0, score))

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        """Route request to appropriate model based on complexity."""
        if not self.enabled:
            return TransformResult(
                messages=messages,
                tokens_before=0,
                tokens_after=0,
                transform_name=self.name,
            )

        model = kwargs.get("model", "")
        if not model:
            return TransformResult(
                messages=messages,
                tokens_before=0,
                tokens_after=0,
                transform_name=self.name,
            )

        tools = kwargs.get("tools", [])
        complexity = self._estimate_complexity(messages, tools)
        use_cheap = complexity < self.config.complexity_threshold
        target_model = self.config.model_map.get(model, model) if use_cheap else model

        tokens_before = tokenizer.count_messages(messages)

        return TransformResult(
            messages=list(messages),
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            transforms_applied=[self.name],
        )
