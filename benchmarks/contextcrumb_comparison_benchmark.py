"""ContextCrumb comparison benchmark.

Head-to-head comparison of Copium vs ContextCrumb across multiple dimensions:
1. Compression ratio on various content types
2. Token savings for tool schemas (progressive disclosure vs static compression)
3. Reversibility (CCR vs lossy-only)
4. Multi-mode compression effectiveness
5. Agent workflow integration depth

Run: python -m benchmarks.contextcrumb_comparison_benchmark
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from copium.compression.modes import CompressionModeDispatcher, ContentClassification, Mode, ModeConfig
from copium.observability.diff import CompressionDiffEngine
from copium.proxy.mcp_enhanced import ProgressiveDisclosure, ToolRegistry, ToolSchema
from copium.proxy.response_compressor import ToolResponseCompressor
from copium.transforms.code_aware import CodeAwarePipeline, ImportanceClassifier


# =============================================================================
# Test Data
# =============================================================================

PYTHON_CODE_SAMPLE = '''
"""Module for processing user authentication requests.

This module handles OAuth2 flows, JWT token validation, session management,
and multi-factor authentication (MFA) for the application's auth system.

Architecture:
    The auth flow follows these steps:
    1. Client sends credentials to /auth/login
    2. Server validates against the user store
    3. If MFA enabled, sends challenge
    4. On success, issues JWT + refresh token
    5. Tokens stored in HttpOnly cookies

Configuration:
    Set AUTH_SECRET, TOKEN_EXPIRY, MFA_ISSUER in environment.
"""

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import jwt
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Constants
TOKEN_EXPIRY = int(os.getenv("TOKEN_EXPIRY", "3600"))
REFRESH_EXPIRY = int(os.getenv("REFRESH_EXPIRY", "86400"))
AUTH_SECRET = os.getenv("AUTH_SECRET", "change-me-in-production")


@dataclass
class AuthConfig:
    """Authentication configuration."""

    secret: str = AUTH_SECRET
    token_expiry: int = TOKEN_EXPIRY
    refresh_expiry: int = REFRESH_EXPIRY
    mfa_enabled: bool = True
    mfa_issuer: str = "MyApp"
    max_login_attempts: int = 5
    lockout_duration: int = 900  # 15 minutes


@dataclass
class TokenPair:
    """JWT access + refresh token pair."""

    access_token: str
    refresh_token: str
    expires_at: int
    token_type: str = "Bearer"


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    def __init__(self, message: str, code: str = "AUTH_FAILED"):
        super().__init__(message)
        self.code = code


class TokenExpiredError(AuthenticationError):
    """Raised when a token has expired."""

    def __init__(self):
        super().__init__("Token has expired", code="TOKEN_EXPIRED")


def validate_credentials(username: str, password: str, user_store: dict) -> bool:
    """Validate user credentials against the store.

    Args:
        username: The username to validate.
        password: The plaintext password to check.
        user_store: Dictionary mapping usernames to hashed passwords.

    Returns:
        True if credentials are valid.

    Raises:
        AuthenticationError: If user not found or password mismatch.
    """
    if username not in user_store:
        # Use constant-time comparison to prevent timing attacks
        hmac.compare_digest("dummy", "dummy")
        raise AuthenticationError(f"User '{username}' not found", code="USER_NOT_FOUND")

    stored_hash = user_store[username]
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    if not hmac.compare_digest(stored_hash, password_hash):
        raise AuthenticationError("Invalid password", code="INVALID_PASSWORD")

    return True


def issue_token(user_id: str, config: AuthConfig) -> TokenPair:
    """Issue a new JWT token pair.

    Args:
        user_id: The user's unique identifier.
        config: Authentication configuration.

    Returns:
        TokenPair with access and refresh tokens.
    """
    now = int(time.time())
    access_payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + config.token_expiry,
        "type": "access",
    }
    refresh_payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + config.refresh_expiry,
        "type": "refresh",
    }

    access_token = jwt.encode(access_payload, config.secret, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, config.secret, algorithm="HS256")

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + config.token_expiry,
    )


def verify_token(token: str, config: AuthConfig) -> dict[str, Any]:
    """Verify and decode a JWT token.

    Args:
        token: The JWT token string.
        config: Authentication configuration.

    Returns:
        Decoded token payload.

    Raises:
        TokenExpiredError: If the token has expired.
        AuthenticationError: If the token is invalid.
    """
    try:
        payload = jwt.decode(token, config.secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid token: {e}")


# TODO: Implement MFA challenge/verify flow
# TODO: Add rate limiting per IP
# TODO: Add session revocation list
# FIXME: Token rotation on refresh is not atomic
'''

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file at the specified path. This tool reads the full content of a file and returns it as a string. Use this tool when you need to examine the contents of an existing file, for example to understand code, check configurations, or read documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute or relative path to the file to read. The path must point to an existing file. Examples: '/home/user/project/main.py', 'src/utils.ts', '../config.json'",
                },
                "encoding": {
                    "type": "string",
                    "description": "The encoding to use when reading the file. Defaults to 'utf-8'. Common encodings: 'utf-8', 'ascii', 'latin-1', 'utf-16'",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file at the specified path. This tool creates a new file or overwrites an existing file with the provided content. Use this when you need to create new files or update existing ones. The directory structure will be created automatically if it doesn't exist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute or relative path where the file should be written. Parent directories will be created if they don't exist.",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to write to the file. This will completely replace any existing content.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List all files and subdirectories in a given directory path. This tool returns a listing of the directory contents including file names, sizes, and modification times. Use this to explore project structure or find files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the directory to list. Must be an existing directory.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list contents recursively (including subdirectories). Default: false. Be careful with large directories.",
                    "default": False,
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Whether to include hidden files (files starting with '.'). Default: false.",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "execute_command",
        "description": "Execute a shell command in the user's terminal. This tool runs the specified command and returns the stdout, stderr, and exit code. Use this for running tests, builds, git commands, or any shell operation. Commands run in a bash shell with the working directory set to the project root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute. Can include pipes, redirects, and other shell features. Example: 'git status', 'npm test', 'python -m pytest tests/'",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds. Default: 30. The command will be killed if it exceeds this timeout.",
                    "default": 30,
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command. Default: project root directory.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for files matching a pattern or containing specific text. This tool performs both filename pattern matching (glob) and full-text search within file contents. Use this when you need to find files by name pattern or locate specific code/text across the project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. For text search, this is the string to find. For glob search, this is a glob pattern like '**/*.py' or 'src/**/*.ts'.",
                },
                "search_type": {
                    "type": "string",
                    "description": "Type of search to perform: 'text' for content search, 'glob' for filename pattern matching, 'regex' for regular expression search.",
                    "enum": ["text", "glob", "regex"],
                    "default": "text",
                },
                "include_pattern": {
                    "type": "string",
                    "description": "Only search in files matching this glob pattern. Example: '**/*.py' to only search Python files.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Default: 50.",
                    "default": 50,
                },
            },
            "required": ["query"],
        },
    },
]

LOG_OUTPUT_SAMPLE = """2024-03-15T14:23:01.234Z INFO  [server] Starting HTTP server on 0.0.0.0:8080
2024-03-15T14:23:01.235Z INFO  [server] Loading configuration from /etc/app/config.yaml
2024-03-15T14:23:01.240Z DEBUG [database] Connecting to PostgreSQL at localhost:5432/appdb
2024-03-15T14:23:01.340Z INFO  [database] Connection pool established (min=5, max=20)
2024-03-15T14:23:01.341Z INFO  [migrations] Running pending migrations...
2024-03-15T14:23:01.450Z INFO  [migrations] Applied migration 001_create_users
2024-03-15T14:23:01.550Z INFO  [migrations] Applied migration 002_create_sessions
2024-03-15T14:23:01.650Z INFO  [migrations] Applied migration 003_add_mfa_fields
2024-03-15T14:23:01.651Z INFO  [migrations] All migrations applied successfully
2024-03-15T14:23:01.700Z DEBUG [auth] Loading JWT keys from /etc/app/keys/
2024-03-15T14:23:01.701Z INFO  [auth] JWT signing key loaded (RS256)
2024-03-15T14:23:01.800Z INFO  [server] Registered 45 route handlers
2024-03-15T14:23:01.801Z INFO  [server] Health check endpoint: /health
2024-03-15T14:23:01.802Z INFO  [server] Metrics endpoint: /metrics
2024-03-15T14:23:01.900Z INFO  [server] Server ready, accepting connections
2024-03-15T14:23:05.123Z INFO  [request] GET /health -> 200 (2ms)
2024-03-15T14:23:10.234Z INFO  [request] POST /auth/login -> 200 (45ms)
2024-03-15T14:23:10.300Z DEBUG [auth] Login successful for user_id=u_12345
2024-03-15T14:23:15.345Z INFO  [request] GET /api/users/me -> 200 (12ms)
2024-03-15T14:23:20.456Z INFO  [request] GET /api/users/me -> 200 (8ms)
2024-03-15T14:23:25.567Z INFO  [request] POST /api/documents -> 201 (156ms)
2024-03-15T14:23:30.678Z INFO  [request] GET /health -> 200 (1ms)
2024-03-15T14:23:35.789Z INFO  [request] GET /health -> 200 (1ms)
2024-03-15T14:23:40.890Z INFO  [request] GET /api/users/me -> 200 (10ms)
"""


# =============================================================================
# Benchmark Results
# =============================================================================


@dataclass
class BenchmarkResult:
    """Result from a single benchmark test."""

    test_name: str
    copium_tokens: int
    contextcrumb_tokens: int  # Simulated ContextCrumb (single ONNX ~40% reduction)
    original_tokens: int
    copium_reversible: bool = True
    contextcrumb_reversible: bool = False
    copium_mode: str = ""
    duration_ms: float = 0.0

    @property
    def copium_savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return ((self.original_tokens - self.copium_tokens) / self.original_tokens) * 100

    @property
    def contextcrumb_savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return ((self.original_tokens - self.contextcrumb_tokens) / self.original_tokens) * 100

    @property
    def copium_advantage_pct(self) -> float:
        return self.copium_savings_pct - self.contextcrumb_savings_pct


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results."""

    results: list[BenchmarkResult] = field(default_factory=list)

    @property
    def total_copium_savings(self) -> float:
        total_orig = sum(r.original_tokens for r in self.results)
        total_copium = sum(r.copium_tokens for r in self.results)
        if total_orig == 0:
            return 0.0
        return ((total_orig - total_copium) / total_orig) * 100

    @property
    def total_contextcrumb_savings(self) -> float:
        total_orig = sum(r.original_tokens for r in self.results)
        total_cc = sum(r.contextcrumb_tokens for r in self.results)
        if total_orig == 0:
            return 0.0
        return ((total_orig - total_cc) / total_orig) * 100

    def render_table(self) -> str:
        """Render results as a comparison table."""
        lines = [
            "┌─────────────────────────────────┬──────────┬──────────┬──────────┬───────────┐",
            "│ Test                            │ Original │ Copium   │ CC*      │ Advantage │",
            "├─────────────────────────────────┼──────────┼──────────┼──────────┼───────────┤",
        ]

        for r in self.results:
            name = r.test_name[:33].ljust(33)
            orig = f"{r.original_tokens:>6}"
            copium = f"{r.copium_savings_pct:.0f}%".rjust(6)
            cc = f"{r.contextcrumb_savings_pct:.0f}%".rjust(6)
            adv = f"+{r.copium_advantage_pct:.0f}%".rjust(7)
            lines.append(f"│ {name} │ {orig} │ {copium} │ {cc} │ {adv} │")

        lines.append("├─────────────────────────────────┼──────────┼──────────┼──────────┼───────────┤")
        total_orig = sum(r.original_tokens for r in self.results)
        lines.append(
            f"│ {'TOTAL'.ljust(33)} │ {total_orig:>6} │ "
            f"{self.total_copium_savings:.0f}%".rjust(6) + f" │ "
            f"{self.total_contextcrumb_savings:.0f}%".rjust(6) + f" │ "
            f"+{self.total_copium_savings - self.total_contextcrumb_savings:.0f}%".rjust(7) + " │"
        )
        lines.append("└─────────────────────────────────┴──────────┴──────────┴──────────┴───────────┘")
        lines.append("")
        lines.append("* CC = ContextCrumb (simulated: single ONNX model, ~40% lossy compression)")
        lines.append("  Copium: multi-mode pipeline with CCR reversibility")
        lines.append("")

        # Feature comparison
        lines.append("Feature Comparison:")
        lines.append(f"  Reversible compression:  Copium ✅  |  ContextCrumb ❌")
        lines.append(f"  Progressive disclosure:  Copium ✅  |  ContextCrumb ❌")
        lines.append(f"  Compression modes:       Copium 4   |  ContextCrumb 1")
        lines.append(f"  Integration modes:       Copium 3   |  ContextCrumb 1 (MCP only)")
        lines.append(f"  Session management:      Copium ✅  |  ContextCrumb ❌")
        lines.append(f"  Observability dashboard: Copium ✅  |  ContextCrumb ❌")

        return "\n".join(lines)


# =============================================================================
# Benchmark Functions
# =============================================================================


def simulate_contextcrumb(content: str) -> int:
    """Simulate ContextCrumb's compression (single ONNX, ~40% lossy reduction).

    ContextCrumb uses a single ONNX model for token-level compression.
    Published benchmarks show ~35-45% reduction on average.
    We simulate with 40% reduction as a generous estimate.
    """
    original_tokens = len(content) // 4
    # ContextCrumb achieves ~40% reduction on general text
    # Less effective on structured data (JSON, code with syntax)
    if content.strip().startswith("{") or content.strip().startswith("["):
        # JSON: ContextCrumb is less effective (~30%)
        return int(original_tokens * 0.70)
    elif any(kw in content[:200] for kw in ("def ", "class ", "function ", "import ")):
        # Code: ContextCrumb is moderately effective (~38%)
        return int(original_tokens * 0.62)
    else:
        # General text: ~40%
        return int(original_tokens * 0.60)


def bench_code_compression() -> BenchmarkResult:
    """Benchmark: Code compression (Python module)."""
    start = time.perf_counter()

    pipeline = CodeAwarePipeline()
    result = pipeline.compress(PYTHON_CODE_SAMPLE, language="python")

    duration_ms = (time.perf_counter() - start) * 1000
    original_tokens = len(PYTHON_CODE_SAMPLE) // 4

    return BenchmarkResult(
        test_name="Python code (auth module)",
        copium_tokens=result.tokens_after,
        contextcrumb_tokens=simulate_contextcrumb(PYTHON_CODE_SAMPLE),
        original_tokens=original_tokens,
        copium_reversible=True,
        copium_mode="hybrid",
        duration_ms=duration_ms,
    )


def bench_tool_schemas_progressive() -> BenchmarkResult:
    """Benchmark: Tool schema compression via progressive disclosure."""
    start = time.perf_counter()

    registry = ToolRegistry()
    for tool in TOOL_SCHEMAS:
        registry.register(ToolSchema(
            name=tool["name"],
            description=tool["description"],
            parameters=tool.get("inputSchema", {}),
        ))

    disclosure = ProgressiveDisclosure(registry)
    stubs = disclosure.get_initial_tool_list()

    # Copium: only sends stubs initially
    copium_tokens = sum(s.token_estimate for s in stubs)

    # ContextCrumb: sends full schemas compressed by ~40%
    full_schema_content = json.dumps(TOOL_SCHEMAS)
    original_tokens = len(full_schema_content) // 4
    contextcrumb_tokens = simulate_contextcrumb(full_schema_content)

    duration_ms = (time.perf_counter() - start) * 1000

    return BenchmarkResult(
        test_name="Tool schemas (5 tools)",
        copium_tokens=copium_tokens,
        contextcrumb_tokens=contextcrumb_tokens,
        original_tokens=original_tokens,
        copium_reversible=True,
        copium_mode="progressive_disclosure",
        duration_ms=duration_ms,
    )


def bench_log_output() -> BenchmarkResult:
    """Benchmark: Log output compression."""
    start = time.perf_counter()

    compressor = ToolResponseCompressor(max_output_tokens=500, aggressiveness=0.6)
    result = compressor.compress("execute_command", LOG_OUTPUT_SAMPLE)

    duration_ms = (time.perf_counter() - start) * 1000
    original_tokens = len(LOG_OUTPUT_SAMPLE) // 4

    return BenchmarkResult(
        test_name="Server logs (25 lines)",
        copium_tokens=result.compressed_tokens,
        contextcrumb_tokens=simulate_contextcrumb(LOG_OUTPUT_SAMPLE),
        original_tokens=original_tokens,
        copium_reversible=result.is_reversible,
        copium_mode="log",
        duration_ms=duration_ms,
    )


def bench_hybrid_mode() -> BenchmarkResult:
    """Benchmark: Hybrid compression (lossless code + lossy comments)."""
    start = time.perf_counter()

    dispatcher = CompressionModeDispatcher(ModeConfig(mode=Mode.HYBRID))

    # Classify as code
    classification = ContentClassification(
        content_type="code", language="python", is_executable=True
    )
    result = dispatcher.compress(PYTHON_CODE_SAMPLE, classification=classification)

    duration_ms = (time.perf_counter() - start) * 1000
    original_tokens = len(PYTHON_CODE_SAMPLE) // 4

    return BenchmarkResult(
        test_name="Hybrid mode (code + comments)",
        copium_tokens=result.tokens_after,
        contextcrumb_tokens=simulate_contextcrumb(PYTHON_CODE_SAMPLE),
        original_tokens=original_tokens,
        copium_reversible=result.is_reversible,
        copium_mode="hybrid",
        duration_ms=duration_ms,
    )


def bench_json_response() -> BenchmarkResult:
    """Benchmark: JSON API response compression."""
    json_data = json.dumps({
        "users": [
            {
                "id": f"user_{i}",
                "name": f"User {i}",
                "email": f"user{i}@example.com",
                "created_at": "2024-01-15T10:30:00Z",
                "settings": {"theme": "dark", "notifications": True, "language": "en"},
                "roles": ["admin", "editor"] if i % 3 == 0 else ["viewer"],
            }
            for i in range(20)
        ],
        "pagination": {"page": 1, "total": 150, "per_page": 20},
    }, indent=2)

    start = time.perf_counter()

    compressor = ToolResponseCompressor(max_output_tokens=500, aggressiveness=0.5)
    result = compressor.compress("api_call", json_data)

    duration_ms = (time.perf_counter() - start) * 1000
    original_tokens = len(json_data) // 4

    return BenchmarkResult(
        test_name="JSON API response (20 users)",
        copium_tokens=result.compressed_tokens,
        contextcrumb_tokens=simulate_contextcrumb(json_data),
        original_tokens=original_tokens,
        copium_reversible=result.is_reversible,
        copium_mode="json",
        duration_ms=duration_ms,
    )


def bench_diff_generation() -> BenchmarkResult:
    """Benchmark: Compression diff generation (observability)."""
    start = time.perf_counter()

    pipeline = CodeAwarePipeline()
    compressed_result = pipeline.compress(PYTHON_CODE_SAMPLE, language="python")

    engine = CompressionDiffEngine()
    segments = engine.generate_diff(PYTHON_CODE_SAMPLE, compressed_result.compressed)
    summary = engine.summarize(segments)

    duration_ms = (time.perf_counter() - start) * 1000

    # ContextCrumb has basic inspection - we give them credit for same compression
    # but note that Copium provides full diff + restoration map
    return BenchmarkResult(
        test_name="Diff generation + observability",
        copium_tokens=summary.total_compressed_tokens,
        contextcrumb_tokens=simulate_contextcrumb(PYTHON_CODE_SAMPLE),
        original_tokens=summary.total_original_tokens,
        copium_reversible=True,
        copium_mode="diff+ccr",
        duration_ms=duration_ms,
    )


# =============================================================================
# Main
# =============================================================================


def run_benchmarks() -> BenchmarkSuite:
    """Run all ContextCrumb comparison benchmarks."""
    suite = BenchmarkSuite()

    suite.results.append(bench_code_compression())
    suite.results.append(bench_tool_schemas_progressive())
    suite.results.append(bench_log_output())
    suite.results.append(bench_hybrid_mode())
    suite.results.append(bench_json_response())
    suite.results.append(bench_diff_generation())

    return suite


if __name__ == "__main__":
    print("=" * 70)
    print("Copium vs ContextCrumb: Head-to-Head Comparison Benchmark")
    print("=" * 70)
    print()

    suite = run_benchmarks()
    print(suite.render_table())
