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

    Usage:
        router = ModelRouter(config)
        result = router.apply(messages, tokenizer, model="gpt-4o", tools=tools)
        # Check router.target_model to get the routed model
    """

    name = "model_router"

    def __init__(self, config: ModelRouterConfig | None = None) -> None:
        self.config = config or ModelRouterConfig()
        self._target_model: str | None = None
        self._complexity: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def target_model(self) -> str | None:
        """The model this router selected. None if routing was not performed."""
        return self._target_model

    @property
    def complexity(self) -> float:
        """The computed complexity score (0.0-1.0)."""
        return self._complexity

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
        """Route request to appropriate model based on complexity.

        After calling this, check self.target_model for the routed model.
        If routing is disabled or model is not in model_map, target_model
        will be the same as the input model.
        """
        self._target_model = None
        self._complexity = 0.0

        if not self.enabled:
            return TransformResult(
                messages=list(messages),
                tokens_before=tokenizer.count_messages(messages),
                tokens_after=tokenizer.count_messages(messages),
                transforms_applied=[],
            )

        model = kwargs.get("model", "")
        if not model:
            return TransformResult(
                messages=list(messages),
                tokens_before=tokenizer.count_messages(messages),
                tokens_after=tokenizer.count_messages(messages),
                transforms_applied=[],
            )

        tools = kwargs.get("tools", [])
        self._complexity = self._estimate_complexity(messages, tools)
        use_cheap = self._complexity < self.config.complexity_threshold
        target = self.config.model_map.get(model, model) if use_cheap else model

        self._target_model = target
        tokens_before = tokenizer.count_messages(messages)

        transforms = []
        if target != model:
            transforms.append(f"model_router:{model}->{target}:complexity={self._complexity:.2f}")

        return TransformResult(
            messages=list(messages),
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            transforms_applied=transforms,
        )
