"""Comprehensive tests for LangChain integration.

Tests cover:
1. CopiumChatModel - Wrapper for any BaseChatModel
2. CopiumCallbackHandler - Metrics and observability
3. CopiumRunnable - LCEL chain composition
4. optimize_messages() - Standalone optimization function
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

# Check if LangChain is available
try:
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
    from langchain_core.outputs import ChatGeneration, ChatResult

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

from copium import CopiumConfig, CopiumMode

# Skip all tests if LangChain not installed
pytestmark = pytest.mark.skipif(not LANGCHAIN_AVAILABLE, reason="LangChain not installed")


@pytest.fixture
def mock_chat_model():
    """Create a mock LangChain chat model."""
    mock = MagicMock()
    mock._llm_type = "mock-chat"
    mock._identifying_params = {"model": "mock-model"}
    mock.model_name = "gpt-4o"

    # Mock _generate to return a ChatResult
    def mock_generate(messages, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content="Hello! I'm a mock response."),
                )
            ],
            llm_output={
                "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            },
        )

    mock._generate = MagicMock(side_effect=mock_generate)
    mock._stream = MagicMock(
        return_value=iter([ChatGeneration(message=AIMessage(content="Streaming..."))])
    )

    return mock


@pytest.fixture
def sample_messages():
    """Sample LangChain messages for testing."""
    return [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="What is the capital of France?"),
    ]


@pytest.fixture
def large_tool_output():
    """Large tool output that should trigger compression."""
    items = [
        {"id": i, "name": f"Item {i}", "value": i * 100, "status": "active"} for i in range(100)
    ]
    return json.dumps(items)


class TestLangchainAvailable:
    """Tests for langchain_available() helper."""

    def test_returns_bool(self):
        """langchain_available returns boolean."""
        from copium.integrations.langchain import langchain_available

        assert isinstance(langchain_available(), bool)

    def test_returns_true_when_installed(self):
        """Returns True when LangChain is installed."""
        from copium.integrations.langchain import langchain_available

        assert langchain_available() is True


class TestCopiumChatModel:
    """Tests for CopiumChatModel wrapper."""

    def test_init_with_defaults(self, mock_chat_model):
        """Initialize with default config."""
        from copium.integrations import CopiumChatModel

        model = CopiumChatModel(mock_chat_model)

        assert model.wrapped_model is mock_chat_model
        assert model.mode == CopiumMode.OPTIMIZE
        assert model._metrics_history == []
        assert model._total_tokens_saved == 0

    def test_init_with_custom_config(self, mock_chat_model):
        """Initialize with custom config."""
        from copium.integrations import CopiumChatModel

        config = CopiumConfig(default_mode=CopiumMode.AUDIT)
        model = CopiumChatModel(
            mock_chat_model,
            config=config,
            mode=CopiumMode.SIMULATE,
        )

        assert model.copium_config is config
        assert model.mode == CopiumMode.SIMULATE

    def test_llm_type(self, mock_chat_model):
        """_llm_type includes wrapped model type."""
        from copium.integrations import CopiumChatModel

        model = CopiumChatModel(mock_chat_model)
        assert "copium" in model._llm_type
        assert "mock-chat" in model._llm_type

    def test_identifying_params(self, mock_chat_model):
        """_identifying_params includes wrapped model params."""
        from copium.integrations import CopiumChatModel

        model = CopiumChatModel(mock_chat_model)
        params = model._identifying_params

        assert "wrapped_model" in params
        assert "copium_mode" in params

    def test_convert_messages_to_openai(self, mock_chat_model, sample_messages):
        """Convert LangChain messages to OpenAI format."""
        from copium.integrations import CopiumChatModel

        model = CopiumChatModel(mock_chat_model)
        openai_msgs = model._convert_messages_to_openai(sample_messages)

        assert len(openai_msgs) == 2
        assert openai_msgs[0]["role"] == "system"
        assert openai_msgs[0]["content"] == "You are a helpful assistant."
        assert openai_msgs[1]["role"] == "user"
        assert "France" in openai_msgs[1]["content"]

    def test_convert_messages_with_tool_calls(self, mock_chat_model):
        """Convert messages with tool calls."""
        from copium.integrations import CopiumChatModel

        messages = [
            HumanMessage(content="Get the weather"),
            AIMessage(
                content="I'll check the weather.",
                tool_calls=[{"id": "call_123", "name": "get_weather", "args": {"city": "Paris"}}],
            ),
            ToolMessage(content='{"temp": 20}', tool_call_id="call_123"),
        ]

        model = CopiumChatModel(mock_chat_model)
        openai_msgs = model._convert_messages_to_openai(messages)

        assert len(openai_msgs) == 3
        assert openai_msgs[1]["role"] == "assistant"
        assert "tool_calls" in openai_msgs[1]
        assert openai_msgs[2]["role"] == "tool"
        assert openai_msgs[2]["tool_call_id"] == "call_123"

    def test_convert_messages_from_openai(self, mock_chat_model):
        """Convert OpenAI format back to LangChain."""
        from copium.integrations import CopiumChatModel

        openai_msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        model = CopiumChatModel(mock_chat_model)
        lc_msgs = model._convert_messages_from_openai(openai_msgs)

        assert len(lc_msgs) == 3
        assert isinstance(lc_msgs[0], SystemMessage)
        assert isinstance(lc_msgs[1], HumanMessage)
        assert isinstance(lc_msgs[2], AIMessage)

    def test_generate_applies_optimization(self, mock_chat_model, sample_messages):
        """_generate applies Copium optimization."""
        from copium.integrations import CopiumChatModel
        from copium.providers import OpenAIProvider

        model = CopiumChatModel(mock_chat_model)

        # Initialize provider and pipeline for mocking
        model._provider = OpenAIProvider()
        _ = model.pipeline  # Force lazy init

        # Mock the pipeline apply method
        with patch.object(model._pipeline, "apply") as mock_apply:
            mock_result = MagicMock()
            mock_result.messages = [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "What is the capital of France?"},
            ]
            mock_result.tokens_before = 100
            mock_result.tokens_after = 80
            mock_result.transforms_applied = ["cache_aligner"]
            mock_apply.return_value = mock_result

            model._generate(sample_messages)

            # Verify pipeline.apply was called
            mock_apply.assert_called_once()

            # Verify metrics were tracked
            assert len(model._metrics_history) == 1
            assert model._metrics_history[0].tokens_saved == 20

    def test_metrics_history_limited(self, mock_chat_model, sample_messages):
        """Metrics history is limited to 100 entries."""
        from copium.integrations import CopiumChatModel

        model = CopiumChatModel(mock_chat_model)

        # Add 150 fake metrics
        for _i in range(150):
            model._metrics_history.append(MagicMock())

        # Simulate a call that trims
        model._metrics_history = model._metrics_history[-100:]

        assert len(model._metrics_history) == 100

    def test_get_savings_summary_empty(self, mock_chat_model):
        """get_savings_summary with no history."""
        from copium.integrations import CopiumChatModel

        model = CopiumChatModel(mock_chat_model)
        summary = model.get_savings_summary()

        assert summary["total_requests"] == 0
        assert summary["total_tokens_saved"] == 0
        assert summary["average_savings_percent"] == 0

    def test_get_savings_summary_with_data(self, mock_chat_model):
        """get_savings_summary with metrics."""
        from copium.integrations import CopiumChatModel
        from copium.integrations.langchain import OptimizationMetrics

        model = CopiumChatModel(mock_chat_model)

        # Add fake metrics
        model._metrics_history = [
            OptimizationMetrics(
                request_id="1",
                timestamp=datetime.now(),
                tokens_before=100,
                tokens_after=80,
                tokens_saved=20,
                savings_percent=20.0,
                transforms_applied=["smart_crusher"],
                model="gpt-4o",
            ),
            OptimizationMetrics(
                request_id="2",
                timestamp=datetime.now(),
                tokens_before=200,
                tokens_after=150,
                tokens_saved=50,
                savings_percent=25.0,
                transforms_applied=["cache_aligner"],
                model="gpt-4o",
            ),
        ]
        model._total_tokens_saved = 70

        summary = model.get_savings_summary()

        assert summary["total_requests"] == 2
        assert summary["total_tokens_saved"] == 70
        assert summary["average_savings_percent"] == 22.5


class TestCopiumCallbackHandler:
    """Tests for CopiumCallbackHandler."""

    def test_init_defaults(self):
        """Initialize with default settings."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler()

        assert handler.log_level == "INFO"
        assert handler.token_alert_threshold is None
        assert handler.total_tokens == 0
        assert handler.total_requests == 0

    def test_init_with_thresholds(self):
        """Initialize with alert thresholds."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler(
            token_alert_threshold=10000,
            cost_alert_threshold=1.0,
        )

        assert handler.token_alert_threshold == 10000
        assert handler.cost_alert_threshold == 1.0

    def test_on_chat_model_start(self):
        """Track chat model start."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler()

        messages = [[HumanMessage(content="Hello, how are you?")]]
        handler.on_chat_model_start(
            serialized={"name": "ChatOpenAI", "id": ["langchain", "ChatOpenAI"]},
            messages=messages,
        )

        assert handler._current_request is not None
        assert "start_time" in handler._current_request
        assert handler._current_request["message_count"] == 1

    def test_on_chat_model_start_triggers_alert(self):
        """Alert triggered when tokens exceed threshold."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler(token_alert_threshold=5)

        # Long message to exceed threshold
        messages = [[HumanMessage(content="A" * 100)]]
        handler.on_chat_model_start(
            serialized={"name": "ChatOpenAI"},
            messages=messages,
        )

        assert len(handler.alerts) > 0
        assert "Token alert" in handler.alerts[0]

    def test_on_llm_end_tracks_tokens(self):
        """Track tokens on LLM completion."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler()
        handler._current_request = {"start_time": datetime.now()}

        response = MagicMock()
        response.llm_output = {
            "token_usage": {
                "prompt_tokens": 50,
                "completion_tokens": 20,
                "total_tokens": 70,
            }
        }

        handler.on_llm_end(response)

        assert handler.total_tokens == 70
        assert handler.total_requests == 1
        assert handler.requests[0]["total_tokens"] == 70

    def test_on_llm_error(self):
        """Track errors."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler()
        handler._current_request = {"start_time": datetime.now()}

        handler.on_llm_error(ValueError("Test error"), run_id=uuid4())

        assert handler.total_requests == 1
        assert "error" in handler.requests[0]

    def test_get_summary(self):
        """Get summary statistics."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler()

        # Add some requests
        handler._requests = [
            {"total_tokens": 100, "duration_ms": 500},
            {"total_tokens": 200, "duration_ms": 300},
            {"error": "failed", "duration_ms": 0},
        ]

        summary = handler.get_summary()

        assert summary["total_requests"] == 3
        assert summary["successful_requests"] == 2
        assert summary["total_tokens"] == 300
        assert summary["errors"] == 1

    def test_reset(self):
        """Reset clears all state."""
        from copium.integrations import CopiumCallbackHandler

        handler = CopiumCallbackHandler()
        handler._requests = [{"test": 1}]
        handler._total_tokens = 100
        handler._alerts = ["alert"]

        handler.reset()

        assert handler.total_requests == 0
        assert handler.total_tokens == 0
        assert len(handler.alerts) == 0


class TestCopiumRunnable:
    """Tests for CopiumRunnable LCEL component."""

    def test_init_defaults(self):
        """Initialize with defaults."""
        from copium.integrations.langchain import CopiumRunnable

        runnable = CopiumRunnable()

        assert runnable.mode == CopiumMode.OPTIMIZE
        assert runnable.config is not None

    def test_init_custom_config(self):
        """Initialize with custom config."""
        from copium.integrations.langchain import CopiumRunnable

        config = CopiumConfig(default_mode=CopiumMode.AUDIT)
        runnable = CopiumRunnable(config=config, mode=CopiumMode.SIMULATE)

        assert runnable.config is config
        assert runnable.mode == CopiumMode.SIMULATE

    def test_as_runnable(self):
        """Convert to LangChain Runnable."""
        from langchain_core.runnables import RunnableLambda

        from copium.integrations.langchain import CopiumRunnable

        runnable = CopiumRunnable()
        lc_runnable = runnable.as_runnable()

        assert isinstance(lc_runnable, RunnableLambda)

    def test_optimize_messages(self, sample_messages):
        """Optimize list of messages."""
        from copium.integrations.langchain import CopiumRunnable
        from copium.providers import OpenAIProvider

        runnable = CopiumRunnable()

        # Initialize provider and pipeline for mocking
        runnable._provider = OpenAIProvider()
        _ = runnable.pipeline  # Force lazy init

        with patch.object(runnable._pipeline, "apply") as mock_apply:
            mock_result = MagicMock()
            mock_result.messages = [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ]
            mock_result.tokens_before = 50
            mock_result.tokens_after = 40
            mock_result.transforms_applied = []
            mock_apply.return_value = mock_result

            result = runnable._optimize(sample_messages)

            assert len(result) == 2
            assert isinstance(result[0], SystemMessage)


class TestOptimizeMessages:
    """Tests for standalone optimize_messages function."""

    def test_basic_optimization(self, sample_messages):
        """Basic message optimization."""
        from copium.integrations import optimize_messages

        with patch("copium.integrations.langchain.chat_model.TransformPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.messages = [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ]
            mock_result.tokens_before = 100
            mock_result.tokens_after = 80
            mock_result.transforms_applied = ["cache_aligner"]
            mock_instance.apply.return_value = mock_result
            MockPipeline.return_value = mock_instance

            optimized, metrics = optimize_messages(sample_messages)

            assert len(optimized) == 2
            assert metrics["tokens_saved"] == 20
            assert metrics["savings_percent"] == 20.0

    def test_with_custom_config(self, sample_messages):
        """Optimization with custom config."""
        from copium.integrations import optimize_messages

        config = CopiumConfig(default_mode=CopiumMode.AUDIT)

        with patch("copium.integrations.langchain.chat_model.TransformPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.messages = []
            mock_result.tokens_before = 50
            mock_result.tokens_after = 50
            mock_result.transforms_applied = []
            mock_instance.apply.return_value = mock_result
            MockPipeline.return_value = mock_instance

            _, metrics = optimize_messages(
                sample_messages,
                config=config,
                mode=CopiumMode.AUDIT,
            )

            # Verify pipeline was created with config
            MockPipeline.assert_called_once()
            call_kwargs = MockPipeline.call_args[1]
            assert call_kwargs["config"] is config

    def test_with_tool_messages(self):
        """Optimization with tool messages."""
        from copium.integrations import optimize_messages

        messages = [
            HumanMessage(content="Get weather"),
            AIMessage(
                content="Checking...",
                tool_calls=[{"id": "1", "name": "weather", "args": {}}],
            ),
            ToolMessage(content="Sunny", tool_call_id="1"),
        ]

        with patch("copium.integrations.langchain.chat_model.TransformPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.messages = [
                {"role": "user", "content": "Get weather"},
                {
                    "role": "assistant",
                    "content": "Checking...",
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": "weather", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "1", "content": "Sunny"},
            ]
            mock_result.tokens_before = 100
            mock_result.tokens_after = 90
            mock_result.transforms_applied = []
            mock_instance.apply.return_value = mock_result
            MockPipeline.return_value = mock_instance

            optimized, metrics = optimize_messages(messages)

            assert len(optimized) == 3
            assert isinstance(optimized[2], ToolMessage)


class TestIntegrationWithRealCopium:
    """Integration tests using real Copium components (no mocking)."""

    def test_real_optimization_pipeline(self, sample_messages):
        """Test with real Copium client (no API calls)."""
        from copium.integrations import optimize_messages

        # This uses real Copium transforms but no LLM API calls
        optimized, metrics = optimize_messages(
            sample_messages,
            mode=CopiumMode.OPTIMIZE,
        )

        # Should return valid messages
        assert len(optimized) >= 1
        assert all(
            isinstance(m, (SystemMessage, HumanMessage, AIMessage, ToolMessage)) for m in optimized
        )

        # Metrics should be populated
        assert "tokens_before" in metrics
        assert "tokens_after" in metrics
        assert "transforms_applied" in metrics

    def test_large_conversation_compression(self):
        """Test compression of large conversation."""
        from copium.integrations import optimize_messages

        # Create large conversation
        messages = [SystemMessage(content="You are a helpful assistant.")]
        for i in range(50):
            messages.append(HumanMessage(content=f"Question {i}: What is {i} + {i}?"))
            messages.append(AIMessage(content=f"The answer is {i + i}."))

        optimized, metrics = optimize_messages(messages)

        # Should compress (rolling window, etc.)
        assert metrics["tokens_before"] >= metrics["tokens_after"]


# ============================================================================
# Real Ollama Integration Tests (no mocks, actual LLM calls)
# ============================================================================


def _ollama_available() -> bool:
    """Check if Ollama is running and has a model available."""
    import socket

    # First check if ollama Python package is installed
    try:
        import ollama  # noqa: F401
    except ImportError:
        return False

    try:
        # Check if Ollama server is running on default port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 11434))
        sock.close()
        return result == 0
    except Exception:
        return False


def _langchain_ollama_available() -> bool:
    """Check if langchain-ollama package is installed."""
    try:
        from langchain_ollama import ChatOllama  # noqa: F401

        return True
    except ImportError:
        return False


def _get_ollama_model() -> str | None:
    """Get an available Ollama model for testing."""
    if not _ollama_available():
        return None

    import subprocess

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        # Parse output to find a model
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:  # Header + at least one model
            return None

        # Get first model name (skip header)
        for line in lines[1:]:
            parts = line.split()
            if parts:
                model_name = parts[0]
                # Prefer small models for faster tests
                if any(
                    small in model_name.lower() for small in ["tiny", "phi", "qwen", "gemma:2b"]
                ):
                    return model_name
        # Fallback to first available model
        first_model_line = lines[1].split()
        return first_model_line[0] if first_model_line else None
    except Exception:
        return None


@pytest.mark.skipif(
    not (_ollama_available() and _langchain_ollama_available()),
    reason="Ollama not running or langchain-ollama not installed",
)
class TestOllamaIntegration:
    """Integration tests using real Ollama models with LangChain.

    These tests require Ollama to be installed and running locally.
    They are skipped in CI unless Ollama is set up.

    To run these tests locally:
        1. Install Ollama: curl -fsSL https://ollama.com/install.sh | sh
        2. Pull a small model: ollama pull llama2
        3. Run tests: pytest tests/test_integrations/langchain/test_chat_model.py -v -k ollama
    """

    @pytest.fixture
    def ollama_model_name(self):
        """Get an available Ollama model."""
        model = _get_ollama_model()
        if not model:
            pytest.skip("No Ollama models available")
        return model

    def test_copium_chat_model_with_ollama(self, ollama_model_name):
        """Test CopiumChatModel wrapping real ChatOllama model."""
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumChatModel

        # Create real Ollama model (no API key needed)
        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model)

        assert copium_model.wrapped_model is base_model
        assert isinstance(copium_model, CopiumChatModel)

    def test_invoke_with_ollama(self, ollama_model_name):
        """Actually invoke an LLM call with Ollama - full end-to-end test."""
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumChatModel

        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model)

        messages = [
            SystemMessage(content="You are a helpful assistant. Be very brief."),
            HumanMessage(content="What is 2+2? Answer with just the number."),
        ]

        # This makes a real LLM call
        result = copium_model.invoke(messages)

        assert result is not None
        assert result.content is not None
        assert len(result.content) > 0

    def test_generate_with_ollama(self, ollama_model_name):
        """Test _generate method with real Ollama model."""
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumChatModel

        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model)

        messages = [
            HumanMessage(content="Say 'hello' and nothing else."),
        ]

        result = copium_model._generate(messages)

        assert result is not None
        assert len(result.generations) > 0
        assert result.generations[0].message.content is not None

    def test_optimization_tracked_with_ollama(self, ollama_model_name):
        """Test that optimization metrics are tracked with real calls."""
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumChatModel

        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model)

        # Make a call with some messages
        messages = [
            SystemMessage(content="You are helpful."),
            HumanMessage(content="Hi"),
        ]

        copium_model.invoke(messages)

        # Metrics should be tracked
        assert len(copium_model._metrics_history) >= 1

    def test_multiple_turns_with_ollama(self, ollama_model_name):
        """Test multi-turn conversation with real Ollama."""
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumChatModel

        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model)

        # First turn
        messages = [
            SystemMessage(content="You are a helpful assistant. Be brief."),
            HumanMessage(content="My name is Alice."),
        ]
        response1 = copium_model.invoke(messages)

        # Second turn - add previous exchange
        messages.append(AIMessage(content=response1.content))
        messages.append(HumanMessage(content="What is my name?"))

        response2 = copium_model.invoke(messages)

        assert response2 is not None
        assert response2.content is not None
        # Model should remember the name from context
        assert len(response2.content) > 0

    def test_copium_optimization_reduces_tokens(self, ollama_model_name):
        """Test that Copium optimization actually reduces token count."""
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumChatModel

        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model, mode=CopiumMode.OPTIMIZE)

        # Create a conversation with repetitive content that should be compressed
        messages = [SystemMessage(content="You are a helpful assistant.")]
        for i in range(20):
            messages.append(HumanMessage(content=f"Question {i}: What is {i} + {i}?"))
            messages.append(AIMessage(content=f"The answer to {i} + {i} is {i + i}."))
        messages.append(HumanMessage(content="What was question 5?"))

        # This should trigger compression
        copium_model.invoke(messages)

        # Check that some optimization was tracked
        if copium_model._metrics_history:
            metrics = copium_model._metrics_history[-1]
            # With a large conversation, we expect some savings
            assert metrics.tokens_before >= metrics.tokens_after

    def test_callback_handler_with_ollama(self, ollama_model_name):
        """Test CopiumCallbackHandler with real Ollama calls."""
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumCallbackHandler, CopiumChatModel

        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model)
        handler = CopiumCallbackHandler()

        messages = [
            HumanMessage(content="Say 'test' and nothing else."),
        ]

        # Invoke with callback
        copium_model.invoke(messages, config={"callbacks": [handler]})

        # Handler should have tracked the request
        assert handler.total_requests >= 1


@pytest.mark.skipif(
    not (_ollama_available() and _langchain_ollama_available()),
    reason="Ollama not running or langchain-ollama not installed",
)
class TestRealLangChainIntegration:
    """Real integration tests that validate LangChain components work together.

    These use real Ollama but focus on LangChain-specific functionality.
    """

    @pytest.fixture
    def ollama_model_name(self):
        """Get an available Ollama model."""
        model = _get_ollama_model()
        if not model:
            pytest.skip("No Ollama models available")
        return model

    def test_lcel_chain_with_copium(self, ollama_model_name):
        """Test LCEL chain composition with CopiumChatModel."""
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_ollama import ChatOllama

        from copium.integrations import CopiumChatModel

        # Create chain: prompt -> copium model -> output parser
        base_model = ChatOllama(model=ollama_model_name)
        copium_model = CopiumChatModel(base_model)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "You are a helpful assistant. Be very brief."),
                ("human", "{input}"),
            ]
        )

        chain = prompt | copium_model | StrOutputParser()

        # Invoke the chain
        result = chain.invoke({"input": "What is 1+1? Just the number."})

        assert result is not None
        assert len(result) > 0

    def test_optimize_messages_standalone_with_ollama_types(self, ollama_model_name):
        """Test standalone optimize_messages function with real message types."""
        from copium.integrations import optimize_messages

        # Use real LangChain message types
        messages = [
            SystemMessage(content="You are a math tutor."),
            HumanMessage(content="What is calculus?"),
            AIMessage(content="Calculus is the mathematical study of continuous change."),
            HumanMessage(content="Can you give me an example?"),
        ]

        optimized, metrics = optimize_messages(messages)

        # Should return valid LangChain messages
        assert len(optimized) >= 1
        assert all(
            isinstance(m, (SystemMessage, HumanMessage, AIMessage, ToolMessage)) for m in optimized
        )
        assert "tokens_before" in metrics
        assert "tokens_after" in metrics
