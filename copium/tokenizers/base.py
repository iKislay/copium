"""Base classes for tokenizer implementations.

Defines the TokenCounter protocol and BaseTokenizer class that all
tokenizer backends must implement.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """Protocol for token counting implementations.

    Any class implementing this protocol can be used with Copium
    for token counting. This allows integration with various
    tokenizer backends (tiktoken, HuggingFace, custom, etc.).
    """

    def count_text(self, text: str) -> int:
        """Count tokens in a text string.

        Args:
            text: The text to count tokens for.

        Returns:
            Number of tokens in the text.
        """
        ...

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        """Count tokens in a list of chat messages.

        Args:
            messages: List of message dicts with 'role' and 'content'.

        Returns:
            Total token count including message overhead.
        """
        ...


class BaseTokenizer(ABC):
    """Abstract base class for tokenizer implementations.

    Provides common functionality for counting messages while
    requiring subclasses to implement text tokenization.
    """

    # Token overhead per message (role, formatting, etc.)
    # Override in subclasses for model-specific overhead
    MESSAGE_OVERHEAD = 4
    REPLY_OVERHEAD = 3  # Assistant reply start tokens

    @abstractmethod
    def count_text(self, text: str) -> int:
        """Count tokens in a text string. Must be implemented by subclasses."""
        pass

    def count_message(self, message: dict[str, Any]) -> int:
        """Count tokens in a single message.

        Args:
            message: A message dict with 'role' and 'content'.

        Returns:
            Token count for this message.
        """
        return self.count_messages([message]) - self.REPLY_OVERHEAD

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        """Count tokens in a list of chat messages.

        Uses OpenAI-style message counting as the baseline, which
        works well for most models.

        Args:
            messages: List of message dicts.

        Returns:
            Total token count.
        """
        total = 0

        for message in messages:
            # Base message overhead
            total += self.MESSAGE_OVERHEAD

            # Count role
            role = message.get("role", "")
            total += self.count_text(role)

            # Count content
            content = message.get("content")
            if content is not None:
                if isinstance(content, str):
                    total += self.count_text(content)
                elif isinstance(content, list):
                    # Multi-part content (images, tool results, etc.)
                    total += self._count_content_parts(content)

            # Count tool calls
            tool_calls = message.get("tool_calls")
            if tool_calls:
                total += self._count_tool_calls(tool_calls)

            # Count function call (legacy)
            function_call = message.get("function_call")
            if function_call:
                total += self._count_function_call(function_call)

            # Count name field
            name = message.get("name")
            if name:
                total += self.count_text(name)
                total += 1  # Name field overhead

        # Reply start overhead
        total += self.REPLY_OVERHEAD

        return total

    def _count_content_parts(self, parts: list[Any]) -> int:
        """Count tokens in multi-part content.

        Handles both Anthropic format ({"type": "text", "text": "..."})
        and Strands SDK format ({"text": "..."} without "type" field).
        """
        total = 0
        for part in parts:
            if isinstance(part, dict):
                part_type = part.get("type", "")

                if part_type == "text":
                    total += self.count_text(part.get("text", ""))
                elif part_type in ("image_url", "image", "input_image"):
                    # Images are NOT tokenized as text — they have a pixel-based cost.
                    # Anthropic: tokens = (width * height) / 750, max ~1600 after resize.
                    # OpenAI: similar tile-based calculation, ~765 tokens for high-detail.
                    # We use 1600 as a conservative estimate (max after auto-resize).
                    # This prevents the base64 blob from being json.dumps'd and counted
                    # as text tokens (1MB image = ~330K fake tokens without this).
                    total += 1600
                elif part_type in ("input_audio", "audio"):
                    # Audio has fixed token cost, not tokenized as text
                    total += 200
                elif part_type == "tool_result":
                    content = part.get("content", "")
                    if isinstance(content, str):
                        total += self.count_text(content)
                    else:
                        total += self.count_text(json.dumps(content))
                elif part_type == "tool_use":
                    total += self.count_text(part.get("name", ""))
                    total += self.count_text(json.dumps(part.get("input", {})))
                elif not part_type and "text" in part:
                    # Strands SDK format: {"text": "..."} without "type" field
                    total += self.count_text(part["text"])
                elif not part_type and "toolUse" in part:
                    # Strands SDK tool_use: {"toolUse": {"name": ..., "input": ...}}
                    tool_use = part["toolUse"]
                    total += self.count_text(tool_use.get("name", ""))
                    total += self.count_text(json.dumps(tool_use.get("input", {})))
                elif not part_type and "toolResult" in part:
                    # Strands SDK tool_result: {"toolResult": {"content": [...]}}
                    tool_result = part["toolResult"]
                    tr_content = tool_result.get("content", [])
                    if isinstance(tr_content, str):
                        total += self.count_text(tr_content)
                    elif isinstance(tr_content, list):
                        # Recurse into nested content blocks
                        total += self._count_content_parts(tr_content)
                    else:
                        total += self.count_text(json.dumps(tr_content))
                elif not part_type and "reasoningContent" in part:
                    # Strands SDK reasoning: {"reasoningContent": {"reasoningText": {"text": "..."}}}
                    # This is actual text — count it precisely.
                    reasoning = part["reasoningContent"]
                    reasoning_text = reasoning.get("reasoningText", {})
                    if isinstance(reasoning_text, dict):
                        total += self.count_text(reasoning_text.get("text", ""))
                    elif isinstance(reasoning_text, str):
                        total += self.count_text(reasoning_text)
                elif not part_type and "document" in part:
                    # Strands SDK document: {"document": {"source": {"bytes": ...}}}
                    # Provider internally extracts text from PDF/DOCX then tokenizes.
                    # Accurate counting would require a PDF parser — instead we use
                    # the Anthropic documented estimate of ~1500 tokens per page,
                    # with ~3KB of PDF per page as a rough heuristic.
                    doc = part["document"]
                    source = doc.get("source", {})
                    doc_bytes = source.get("bytes", b"")
                    if isinstance(doc_bytes, bytes | bytearray):
                        estimated_pages = max(1, len(doc_bytes) // 3000)
                        total += estimated_pages * 1500
                    else:
                        total += self.count_text(str(doc_bytes))
                elif not part_type and "image" in part:
                    # Strands SDK image: {"image": {"source": {"bytes": ...}}}
                    # Anthropic formula: tokens = (width * height) / 750.
                    # Decode with Pillow for exact count; fall back to estimate.
                    total += self._estimate_image_tokens(part["image"])
                elif not part_type and "video" in part:
                    # Strands SDK video: provider samples ~1 fps, each frame costs
                    # image tokens. We can't decode frames without heavy deps, so
                    # estimate from byte size assuming ~30KB per frame, ~1000 tokens
                    # per frame (average image).
                    vid = part["video"]
                    source = vid.get("source", {})
                    vid_bytes = source.get("bytes", b"")
                    if isinstance(vid_bytes, bytes | bytearray):
                        frames = max(1, len(vid_bytes) // 30000)
                        total += frames * 1000
                    else:
                        total += 3200
                else:
                    # Unknown type - estimate from JSON
                    total += self.count_text(json.dumps(part))
            elif isinstance(part, str):
                total += self.count_text(part)

        return total

    @staticmethod
    def _estimate_image_tokens(image_data: dict[str, Any]) -> int:
        """Estimate tokens for an image using Anthropic's formula: (w*h)/750.

        Tries to decode dimensions with Pillow. Falls back to a conservative
        estimate based on byte size.
        """
        source = image_data.get("source", {})
        img_bytes = source.get("bytes", b"")

        if isinstance(img_bytes, bytes | bytearray) and len(img_bytes) > 0:
            try:
                import io

                from PIL import Image

                img = Image.open(io.BytesIO(img_bytes))
                w, h = img.size
                # Anthropic resizes to fit 1568x1568 max
                max_dim = 1568
                if w > max_dim or h > max_dim:
                    scale = max_dim / max(w, h)
                    w, h = int(w * scale), int(h * scale)
                return max(100, (w * h) // 750)
            except Exception:
                pass

        # Fallback: estimate from byte size.
        # Typical screenshot: ~200KB ≈ 1200x800 ≈ 1280 tokens
        if isinstance(img_bytes, bytes | bytearray):
            size_kb = len(img_bytes) / 1024
            if size_kb < 50:
                return 400  # Small icon/thumbnail
            if size_kb < 500:
                return 1200  # Typical screenshot
            return 1600  # Large/high-res image

        return 1200  # Default estimate

    def _count_tool_calls(self, tool_calls: list[dict[str, Any]]) -> int:
        """Count tokens in tool calls."""
        total = 0
        for call in tool_calls:
            total += 4  # Tool call overhead

            if "function" in call:
                func = call["function"]
                total += self.count_text(func.get("name", ""))
                total += self.count_text(func.get("arguments", ""))

            if "id" in call:
                total += self.count_text(call["id"])

        return total

    def _count_function_call(self, function_call: dict[str, Any]) -> int:
        """Count tokens in legacy function call."""
        total = 4  # Function call overhead
        total += self.count_text(function_call.get("name", ""))
        total += self.count_text(function_call.get("arguments", ""))
        return total

    def encode(self, text: str) -> list[int]:
        """Encode text to token IDs.

        Optional method - not all backends support encoding.
        Default implementation raises NotImplementedError.

        Args:
            text: Text to encode.

        Returns:
            List of token IDs.

        Raises:
            NotImplementedError: If encoding is not supported.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support encoding")

    def decode(self, tokens: list[int]) -> str:
        """Decode token IDs to text.

        Optional method - not all backends support decoding.
        Default implementation raises NotImplementedError.

        Args:
            tokens: List of token IDs.

        Returns:
            Decoded text.

        Raises:
            NotImplementedError: If decoding is not supported.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support decoding")
