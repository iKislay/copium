# 005. Integrations

**Status:** done

## Supported Agents

### Claude (`copium/learn/plugins/claude/`)

**Plugin:** `ClaudeLearnPlugin`

**Capabilities:**
- Session branch comparison
- Token copium mode detection
- Tool use tracking
- Multi-modal support (images)

**Interface:**
```python
class ClaudeLearnPlugin(LearnPlugin, ConversationScanner):
    @property
    def name(self) -> str:
        return "claude"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    def detect(self) -> bool:
        """Check if Claude Code has data on the current machine."""
        pass

    def discover_projects(self) -> list[ProjectInfo]:
        """Discover all projects with Claude sessions."""
        pass

    def scan_project(self, project: ProjectInfo, max_workers: int = 1) -> list[SessionData]:
        """Scan all sessions for a project."""
        pass

    def create_writer(self) -> ContextWriter:
        """Return Claude-specific ContextWriter."""
        pass
```

**Configuration:**
```bash
COPIUM_LEARN_CLI=claude
```

---

### Codex (OpenAI) (`copium/learn/plugins/codex/`)

**Plugin:** `CodexLearnPlugin`

**Capabilities:**
- Rate limit handling
- Code completion optimization
- Batch request support

**Interface:**
```python
class CodexLearnPlugin(LearnPlugin, ConversationScanner):
    @property
    def name(self) -> str:
        return "codex"

    @property
    def display_name(self) -> str:
        return "OpenAI Codex"

    def detect(self) -> bool:
        pass

    def discover_projects(self) -> list[ProjectInfo]:
        pass

    def scan_project(self, project: ProjectInfo, max_workers: int = 1) -> list[SessionData]:
        pass

    def create_writer(self) -> ContextWriter:
        pass
```

**Configuration:**
```bash
COPIUM_LEARN_CLI=codex
```

---

### Gemini (Google) (`copium/learn/plugins/gemini/`)

**Plugin:** `GeminiLearnPlugin`

**Capabilities:**
- Multimodal inputs
- Function calling support
- Context caching API

**Interface:**
```python
class GeminiLearnPlugin(LearnPlugin, ConversationScanner):
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Google Gemini"

    def detect(self) -> bool:
        pass

    def discover_projects(self) -> list[ProjectInfo]:
        pass

    def scan_project(self, project: ProjectInfo, max_workers: int = 1) -> list[SessionData]:
        pass

    def create_writer(self) -> ContextWriter:
        pass
```

**Configuration:**
```bash
COPIUM_LEARN_CLI=gemini
```

---

## Integration Points

### LiteLLM Callback (`copium/integrations/litellm_callback.py`)

LiteLLM proxy callback for integrating with LiteLLM-based setups.

**`LiteLLMCallback` class:**
```python
class LiteLLMCallback:
    def __init__(
        self,
        copium_url: str = "http://localhost:8787",
        api_key: str | None = None,
    ) -> None:
        self.copium_url = copium_url
        self.api_key = api_key
    
    def on_completion(self, completion_response: dict) -> dict:
        """Called after completion. Can modify response."""
        pass
    
    def on_error(self, error: Exception) -> None:
        """Called on error."""
        pass
```

**Usage:**
```python
from copium.integrations import LiteLLMCallback

callback = LiteLLMCallback(copium_url="http://localhost:8787")
# Register with LiteLLM proxy
```

---

### ASGI Middleware (`copium/integrations/asgi.py`)

ASGI-compatible middleware for Python web frameworks (FastAPI, Starlette, etc.).

**`CopiumMiddleware` class:**
```python
class CopiumMiddleware:
    def __init__(
        self,
        app: ASGIApplication,
        copium_url: str = "http://localhost:8787",
        mode: ProxyMode = ProxyMode.COMPRESS,
    ) -> None:
        self.app = app
        self.copium_url = copium_url
        self.mode = mode
    
    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """ASGI application interface."""
        pass
```

**Usage:**
```python
from copium.integrations import CopiumMiddleware
from fastapi import FastAPI

app = FastAPI()
app.add_middleware(
    CopiumMiddleware,
    copium_url="http://localhost:8787",
    mode=ProxyMode.COMPRESS,
)
```

---

### MCP integration helpers (`copium/integrations/mcp/server.py`)

Helpers for MCP-aware host applications and custom wrappers. This module does
not currently ship a standalone `CopiumMCPProxy` server implementation.

**`CopiumMCPCompressor` class:**
```python
class CopiumMCPCompressor:
    def __init__(
        self,
        config: CopiumConfig | None = None,
        profiles: list[MCPToolProfile] | None = None,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        ...
    
    def compress(
        self,
        content: str,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        user_query: str = "",
    ) -> MCPCompressionResult:
        """Compress an MCP tool result."""
        pass
```

**Companion helpers:**
- `compress_tool_result(...)` — standalone helper for host applications
- `CopiumMCPClientWrapper` — wraps an MCP client and compresses tool results
- `create_copium_mcp_proxy(...)` — returns config for a custom wrapper/proxy

**Ready-to-run MCP tools server:**
```bash
copium mcp serve
```

---

### Strands (`copium/integrations/strands/`)

Strands framework integration.

**Usage:**
```python
from copium.integrations.strands import CopiumStrandsPlugin

plugin = CopiumStrandsPlugin()
```

---

### LangChain (`copium/integrations/langchain/`)

LangChain callback handler integration.

**`CopiumLangChainCallback` class:**
```python
class CopiumLangChainCallback(BaseCallbackHandler):
    def __init__(
        self,
        copium_url: str = "http://localhost:8787",
        api_key: str | None = None,
    ) -> None:
        self.copium_url = copium_url
        self.api_key = api_key
    
    async def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        pass
    
    async def on_llm_end(self, response, **kwargs) -> None:
        pass
```

**Usage:**
```python
from langchain.callbacks import CopiumLangChainCallback

callback = CopiumLangChainCallback()
# Pass to LangChain chain
```

---

## Agent Contract

All learn plugins must implement the `LearnPlugin` interface:

```python
from abc import ABC, abstractmethod
from copium.learn.base import ConversationScanner, ContextWriter
from copium.learn.models import ProjectInfo, SessionData

class LearnPlugin(ConversationScanner):
    """A self-contained learn plugin for a single coding agent."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short lowercase identifier (e.g., 'claude', 'cursor')."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name (e.g., 'Claude Code', 'Cursor')."""
        ...

    @abstractmethod
    def detect(self) -> bool:
        """Return True if this agent has data on the current machine."""
        ...

    @abstractmethod
    def discover_projects(self) -> list[ProjectInfo]:
        """Discover all projects with conversation data."""
        ...

    @abstractmethod
    def scan_project(self, project: ProjectInfo, max_workers: int = 1) -> list[SessionData]:
        """Scan all sessions for a project."""
        ...

    @abstractmethod
    def create_writer(self) -> ContextWriter:
        """Return the appropriate ContextWriter for this agent."""
        ...
```

**Plugin Registration:**
```python
# Module-level instance for auto-discovery
plugin = MyAgentPlugin()
```

Plugins are auto-discovered from `copium.learn.plugins.*` or via `copium.learn_plugin` entry points.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-draft | 2026-04-16 | Initial integrations document |
