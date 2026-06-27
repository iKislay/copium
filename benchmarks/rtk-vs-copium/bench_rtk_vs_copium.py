"""RTK vs Copium head-to-head benchmark.

Compares compression ratios on identical inputs across CLI stdout,
file reads, search results, and diffs.

Usage:
    python -m benchmarks.rtk-vs-copium.bench_rtk_vs_copium
    pytest benchmarks/rtk-vs-copium/bench_rtk_vs_copium.py -v
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copium.compress import compress
from copium.config import CopiumConfig
from copium.tokenizers import get_tokenizer


# ── Fixtures: real-world CLI outputs ──────────────────────────────────────

GIT_STATUS_FULL = """\
On branch feature/auth-refactor
Your branch is up to date with 'origin/feature/auth-refactor'.

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
\tmodified:   src/auth/handler.rs
\tnew file:   src/auth/oauth2.rs
\tdeleted:    src/auth/legacy.rs

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
\tmodified:   src/main.rs
\tmodified:   tests/auth_test.rs

Untracked files:
  (use "git add <file>..." to include in what will be committed)
\tsrc/auth/mfa.rs
\tdocs/auth-migration.md

"""

GIT_DIFF_FULL = """\
diff --git a/src/auth/handler.rs b/src/auth/handler.rs
index 3a4f2c1..9b7e3d0 100644
--- a/src/auth/handler.rs
+++ b/src/auth/handler.rs
@@ -1,10 +1,15 @@
 use crate::config::AuthConfig;
+use crate::oauth2::OAuth2Provider;
 use std::collections::HashMap;

 pub struct AuthHandler {
     config: AuthConfig,
+    oauth_providers: Vec<OAuth2Provider>,
     sessions: HashMap<String, Session>,
 }

+impl AuthHandler {
+    pub fn new(config: AuthConfig) -> Self {
+        Self {
+            config,
+            oauth_providers: Vec::new(),
+            sessions: HashMap::new(),
+        }
+    }
+}
+
 impl AuthHandler {
     pub fn authenticate(&self, token: &str) -> Result<User, AuthError> {
-        let session = self.sessions.get(token)
-            .ok_or(AuthError::InvalidToken)?;
+        let session = self.sessions.get(token).ok_or(AuthError::InvalidToken)?;
+        if session.is_expired() {
+            return Err(AuthError::SessionExpired);
+        }
         Ok(session.user.clone())
     }
 }
"""

PYTEST_OUTPUT_FULL = """\
============================= test session starts ==============================
platform linux -- Python 3.12.4, pytest-8.3.4, pluggy-1.5.0
rootdir: /home/user/project
configfile: pyproject.toml
plugins: cov-6.0.0, asyncio-0.24.0, mock-3.14.0
collected 247 items

tests/test_auth.py::test_login_success PASSED                        [  0%]
tests/test_auth.py::test_login_invalid_creds PASSED                  [  0%]
tests/test_auth.py::test_login_expired_token PASSED                  [  1%]
tests/test_auth.py::test_oauth_flow PASSED                           [  1%]
tests/test_auth.py::test_mfa_required PASSED                         [  2%]
tests/test_api.py::test_list_users PASSED                            [  2%]
tests/test_api.py::test_create_user PASSED                           [  2%]
tests/test_api.py::test_delete_user PASSED                           [  3%]
tests/test_api.py::test_update_user_permissions PASSED               [  3%]
tests/test_api.py::test_rate_limiting PASSED                         [  4%]
tests/test_api.py::test_pagination PASSED                            [  4%]
tests/test_api.py::test_filtering PASSED                             [  4%]
tests/test_db.py::test_connection_pool PASSED                        [  5%]
tests/test_db.py::test_migration_up PASSED                           [  5%]
tests/test_db.py::test_migration_down PASSED                         [  6%]
tests/test_db.py::test_transaction_rollback PASSED                   [  6%]
tests/test_db.py::test_deadlock_detection PASSED                     [  6%]
tests/test_cache.py::test_redis_get PASSED                           [  7%]
tests/test_cache.py::test_redis_set PASSED                           [  7%]
tests/test_cache.py::test_cache_invalidation PASSED                  [  8%]
tests/test_cache.py::test_cache_ttl PASSED                           [  8%]
tests/test_integration.py::test_full_flow PASSED                     [  8%]
tests/test_integration.py::test_error_handling PASSED                [  9%]
tests/test_integration.py::test_concurrent_requests PASSED           [  9%]
tests/test_integration.py::test_webhook_delivery FAILED              [ 10%]

=================================== FAILURES ===================================
________________________________ test_webhook_delivery _________________________

    def test_webhook_delivery():
        response = client.post("/webhooks/deliver", json={"url": "https://example.com", "payload": {"event": "push"}})
>       assert response.status_code == 200
E       AssertionError: assert 503 == 200
E        +  where 503 = <Response [503]>.status_code

tests/test_integration.py:142: AssertionError
=================================== WARNINGS ===================================
tests/test_cache.py::test_cache_ttl
  /home/user/project/src/cache.py:45: DeprecationWarning: redis.StrictRedis is deprecated
    return redis.StrictRedis(host=self.host, port=self.port)
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_integration.py::test_webhook_delivery - AssertionError: assert 503 == 200
========================= 246 passed, 1 failed, 0 warnings ===================
"""

GREP_OUTPUT_FULL = """\
src/auth/handler.rs:15:    pub fn authenticate(&self, token: &str) -> Result<User, AuthError> {
src/auth/handler.rs:16:        let session = self.sessions.get(token).ok_or(AuthError::InvalidToken)?;
src/auth/handler.rs:17:        if session.is_expired() {
src/auth/handler.rs:18:            return Err(AuthError::SessionExpired);
src/auth/handler.rs:19:        }
src/auth/handler.rs:20:        Ok(session.user.clone())
src/auth/handler.rs:21:    }
src/auth/oauth2.rs:8:    pub fn authenticate_oauth(&self, provider: &str, code: &str) -> Result<User, AuthError> {
src/auth/oauth2.rs:9:        let provider = self.get_provider(provider)?;
src/auth/oauth2.rs:10:        let token = provider.exchange_code(code)?;
src/auth/oauth2.rs:11:        self.validate_token(&token)
src/auth/oauth2.rs:12:    }
src/auth/mfa.rs:22:    pub fn verify_mfa(&self, user: &User, code: &str) -> Result<(), AuthError> {
src/auth/mfa.rs:23:        let secret = self.get_mfa_secret(user)?;
src/auth/mfa.rs:24:        if !totp::verify(secret, code) {
src/auth/mfa.rs:25:            return Err(AuthError::InvalidMfaCode);
src/auth/mfa.rs:26:        }
src/auth/mfa.rs:27:        Ok(())
src/auth/mfa.rs:28:    }
tests/test_auth.rs:5:    fn test_authenticate_valid_token() {
tests/test_auth.rs:14:    fn test_authenticate_invalid_token() {
tests/test_auth.rs:23:    fn test_authenticate_expired_session() {
"""

FILE_READ_LARGE = """\
// src/auth/handler.rs — 200 lines
use crate::config::AuthConfig;
use crate::oauth2::OAuth2Provider;
use std::collections::HashMap;
use std::time::{Duration, Instant};

/// Maximum session lifetime before forced re-authentication.
const MAX_SESSION_DURATION: Duration = Duration::from_secs(3600);

/// Rate limit: max auth attempts per minute per IP.
const MAX_AUTH_ATTEMPTS: u32 = 10;

#[derive(Debug, Clone)]
pub struct Session {
    pub user: User,
    pub created_at: Instant,
    pub last_active: Instant,
    pub ip_address: String,
}

impl Session {
    pub fn is_expired(&self) -> bool {
        self.created_at.elapsed() > MAX_SESSION_DURATION
    }

    pub fn touch(&mut self) {
        self.last_active = Instant::now();
    }
}

#[derive(Debug, Clone)]
pub struct User {
    pub id: String,
    pub email: String,
    pub roles: Vec<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("invalid token")]
    InvalidToken,
    #[error("session expired")]
    SessionExpired,
    #[error("rate limit exceeded")]
    RateLimited,
    #[error("invalid MFA code")]
    InvalidMfaCode,
    #[error("provider error: {0}")]
    ProviderError(String),
}

pub struct AuthHandler {
    config: AuthConfig,
    oauth_providers: Vec<OAuth2Provider>,
    sessions: HashMap<String, Session>,
    rate_limiter: HashMap<String, Vec<Instant>>,
}

impl AuthHandler {
    pub fn new(config: AuthConfig) -> Self {
        Self {
            config,
            oauth_providers: Vec::new(),
            sessions: HashMap::new(),
            rate_limiter: HashMap::new(),
        }
    }

    pub fn authenticate(&self, token: &str) -> Result<User, AuthError> {
        let session = self.sessions.get(token).ok_or(AuthError::InvalidToken)?;
        if session.is_expired() {
            return Err(AuthError::SessionExpired);
        }
        Ok(session.user.clone())
    }

    pub fn create_session(&mut self, user: User, ip: &str) -> Result<String, AuthError> {
        self.check_rate_limit(ip)?;
        let token = self.generate_token();
        let session = Session {
            user,
            created_at: Instant::now(),
            last_active: Instant::now(),
            ip_address: ip.to_string(),
        };
        self.sessions.insert(token.clone(), session);
        Ok(token)
    }

    pub fn revoke_session(&mut self, token: &str) -> bool {
        self.sessions.remove(token).is_some()
    }

    fn check_rate_limit(&mut self, ip: &str) -> Result<(), AuthError> {
        let now = Instant::now();
        let attempts = self.rate_limiter.entry(ip.to_string()).or_default();
        attempts.retain(|t| now.duration_since(*t) < Duration::from_secs(60));
        if attempts.len() >= MAX_AUTH_ATTEMPTS as usize {
            return Err(AuthError::RateLimited);
        }
        attempts.push(now);
        Ok(())
    }

    fn generate_token(&self) -> String {
        use std::iter;
        use rand::Rng;
        let mut rng = rand::thread_rng();
        iter::repeat(())
            .map(|()| rng.sample(rand::distributions::Alphanumeric))
            .map(char::from)
            .take(64)
            .collect()
    }
}
"""


# ── RTK simulation (applies RTK-like compression heuristics) ──────────────

def _simulate_rtk_compression(content: str, content_type: str) -> str:
    """Simulate RTK's stdout compression heuristics.

    RTK strips verbose headers, hint lines, and reformats output
    into a terse format. This simulates that behavior.
    """
    lines = content.splitlines()
    compressed_lines: list[str] = []

    if content_type == "git_status":
        # RTK strips headers and hints, keeps only file status lines
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("On branch"):
                # Keep branch but shorten
                compressed_lines.append(stripped)
            elif stripped.startswith(("modified:", "new file:", "deleted:")):
                compressed_lines.append(f"  {stripped}")
            elif stripped.startswith(("Changes", "Your branch", "(use")):
                continue  # Strip hints
            elif any(c in stripped for c in ("?? ", "M ", "A ", "D ")):
                compressed_lines.append(stripped)
        return "\n".join(compressed_lines)

    elif content_type == "git_diff":
        # RTK keeps diff headers and +/- lines, strips context
        for line in lines:
            if line.startswith(("diff ", "index ", "--- ", "+++ ", "@@")):
                compressed_lines.append(line)
            elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                compressed_lines.append(line)
            # Skip context lines (starting with space)
        return "\n".join(compressed_lines)

    elif content_type == "pytest":
        # RTK strips passing tests, keeps failures and summary
        in_failure = False
        for line in lines:
            if "FAILED" in line or "ERRORS" in line:
                in_failure = True
            if in_failure:
                compressed_lines.append(line)
            elif "passed" in line and ("failed" in line or "error" in line):
                compressed_lines.append(line)
            elif line.startswith("FAILED"):
                compressed_lines.append(line)
        return "\n".join(compressed_lines)

    elif content_type == "grep":
        # RTK passes grep through mostly unchanged (already terse)
        return content

    elif content_type == "file_read":
        # RTK does NOT compress file reads
        return content

    return content


# ── Benchmark runner ──────────────────────────────────────────────────────


@dataclass
class ComparisonResult:
    """Result comparing RTK vs Copium on a single fixture."""

    name: str
    content_type: str
    original_tokens: int
    rtk_tokens: int
    copium_tokens: int
    rtk_savings_pct: float
    copium_savings_pct: float
    copium_advantage_pct: float


def _count_tokens(text: str) -> int:
    """Count tokens using the project tokenizer."""
    tokenizer = get_tokenizer()
    return tokenizer.count(text)


def run_comparison(verbose: bool = False) -> list[ComparisonResult]:
    """Run the RTK vs Copium comparison benchmark."""
    fixtures = [
        ("git status (verbose)", "git_status", GIT_STATUS_FULL),
        ("git diff (auth refactor)", "git_diff", GIT_DIFF_FULL),
        ("pytest output (247 tests, 1 fail)", "pytest", PYTEST_OUTPUT_FULL),
        ("grep results (authenticate)", "grep", GREP_OUTPUT_FULL),
        ("file read (200-line Rust file)", "file_read", FILE_READ_LARGE),
    ]

    config = CopiumConfig()
    results: list[ComparisonResult] = []

    for name, content_type, content in fixtures:
        original_tokens = _count_tokens(content)

        # RTK compression
        rtk_output = _simulate_rtk_compression(content, content_type)
        rtk_tokens = _count_tokens(rtk_output)

        # Copium compression
        messages = [
            {"role": "user", "content": "Show me the output"},
            {"role": "assistant", "content": content},
        ]
        compressed = compress(messages, config=config)
        copium_output = compressed[-1]["content"] if compressed else content
        copium_tokens = _count_tokens(copium_output)

        rtk_savings = (
            (original_tokens - rtk_tokens) / original_tokens * 100
            if original_tokens > 0
            else 0
        )
        copium_savings = (
            (original_tokens - copium_tokens) / original_tokens * 100
            if original_tokens > 0
            else 0
        )
        advantage = copium_savings - rtk_savings

        result = ComparisonResult(
            name=name,
            content_type=content_type,
            original_tokens=original_tokens,
            rtk_tokens=rtk_tokens,
            copium_tokens=copium_tokens,
            rtk_savings_pct=rtk_savings,
            copium_savings_pct=copium_savings,
            copium_advantage_pct=advantage,
        )
        results.append(result)

        if verbose:
            print(f"\n{'─' * 60}")
            print(f"  {name}")
            print(f"  Original: {original_tokens:,} tokens")
            print(f"  RTK:      {rtk_tokens:,} tokens ({rtk_savings:.1f}% saved)")
            print(f"  Copium:   {copium_tokens:,} tokens ({copium_savings:.1f}% saved)")
            print(f"  Copium advantage: +{advantage:.1f}%")

    return results


def print_report(results: list[ComparisonResult]) -> None:
    """Print a formatted comparison report."""
    print("\n" + "═" * 70)
    print("  RTK vs COPIUM — HEAD-TO-HEAD COMPARISON")
    print("═" * 70)
    print(
        f"\n  {'Content Type':<40} {'RTK':>8} {'Copium':>8} {'Δ':>8}"
    )
    print(f"  {'─' * 40} {'─' * 8} {'─' * 8} {'─' * 8}")

    for r in results:
        print(
            f"  {r.name:<40} {r.rtk_savings_pct:>7.1f}% {r.copium_savings_pct:>7.1f}% {r.copium_advantage_pct:>+7.1f}%"
        )

    # Summary
    total_orig = sum(r.original_tokens for r in results)
    total_rtk = sum(r.rtk_tokens for r in results)
    total_copium = sum(r.copium_tokens for r in results)
    rtk_total_pct = (total_orig - total_rtk) / total_orig * 100
    copium_total_pct = (total_orig - total_copium) / total_orig * 100

    print(f"\n  {'─' * 64}")
    print(f"  {'TOTAL':<40} {rtk_total_pct:>7.1f}% {copium_total_pct:>7.1f}% {copium_total_pct - rtk_total_pct:>+7.1f}%")
    print(f"\n  Original tokens: {total_orig:,}")
    print(f"  RTK compressed:  {total_rtk:,} (saved {total_orig - total_rtk:,})")
    print(f"  Copium compressed: {total_copium:,} (saved {total_orig - total_copium:,})")
    print()

    # Key insight
    print("  KEY INSIGHT:")
    print("  RTK only compresses CLI stdout. File reads and search results")
    print("  pass through unchanged. Copium compresses everything.")
    print("═" * 70)


if __name__ == "__main__":
    results = run_comparison(verbose=True)
    print_report(results)
