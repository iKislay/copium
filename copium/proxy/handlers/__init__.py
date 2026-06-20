"""Handler mixins for CopiumProxy.

Each mixin class contains methods extracted from CopiumProxy that handle
requests for a specific provider or concern. The mixins rely on CopiumProxy's
__init__ for all self.* attributes (duck typing).
"""

from copium.proxy.handlers.anthropic import AnthropicHandlerMixin
from copium.proxy.handlers.batch import BatchHandlerMixin
from copium.proxy.handlers.bedrock import BedrockHandlerMixin
from copium.proxy.handlers.gemini import GeminiHandlerMixin
from copium.proxy.handlers.openai import OpenAIHandlerMixin
from copium.proxy.handlers.streaming import StreamingMixin

__all__ = [
    "AnthropicHandlerMixin",
    "BatchHandlerMixin",
    "BedrockHandlerMixin",
    "GeminiHandlerMixin",
    "OpenAIHandlerMixin",
    "StreamingMixin",
]
