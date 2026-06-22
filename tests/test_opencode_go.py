"""Tests for the OpenCode Go integration: model registry and auth loader."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from copium.opencode_go import (
    OPENCODE_GO_MODELS,
    OpenCodeGoAuthLoader,
    get_opencode_go_key,
    is_opencode_go_model,
    reset_auth_loader,
)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


class TestOpenCodeGoModels:
    """Verify the Go model set matches the upstream catalog."""

    @pytest.mark.parametrize(
        "model_id",
        [
            "glm-5.2",
            "glm-5.1",
            "kimi-k2.7-code",
            "kimi-k2.6",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "mimo-v2.5",
            "mimo-v2.5-pro",
        ],
    )
    def test_go_model_recognized(self, model_id: str) -> None:
        assert is_opencode_go_model(model_id)

    @pytest.mark.parametrize(
        "model_id",
        ["gpt-4o", "claude-sonnet-4", "mimo-v2.5-free", "deepseek-v4-flash-free", ""],
    )
    def test_non_go_model_rejected(self, model_id: str) -> None:
        assert not is_opencode_go_model(model_id)

    def test_free_models_not_in_go_set(self) -> None:
        """Free Zen models must NOT route to the Go upstream."""
        free_models = {
            "mimo-v2.5-free",
            "deepseek-v4-flash-free",
            "big-pickle",
            "nemotron-3-ultra-free",
            "north-mini-code-free",
        }
        assert free_models.isdisjoint(OPENCODE_GO_MODELS)

    def test_model_count(self) -> None:
        assert len(OPENCODE_GO_MODELS) == 8


# ---------------------------------------------------------------------------
# Auth loader
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_file(tmp_path: Path) -> Path:
    """Write a temporary auth.json with an opencode-go entry."""
    data = {
        "opencode": {"type": "api", "key": "sk-opencode-fake"},
        "opencode-go": {"type": "api", "key": "sk-go-test-key-12345"},
    }
    p = tmp_path / "auth.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def empty_auth_file(tmp_path: Path) -> Path:
    """Auth.json without an opencode-go entry."""
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"opencode": {"type": "api", "key": "sk-x"}}), encoding="utf-8")
    return p


class TestOpenCodeGoAuthLoader:
    def test_loads_key_from_auth_json(self, auth_file: Path) -> None:
        loader = OpenCodeGoAuthLoader(path=auth_file)
        key = loader.get_key()
        assert key == "sk-go-test-key-12345"

    def test_returns_none_when_no_go_entry(self, empty_auth_file: Path) -> None:
        loader = OpenCodeGoAuthLoader(path=empty_auth_file)
        assert loader.get_key() is None

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        loader = OpenCodeGoAuthLoader(path=tmp_path / "nonexistent.json")
        assert loader.get_key() is None

    def test_returns_none_when_invalid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "auth.json"
        p.write_text("not valid json{", encoding="utf-8")
        loader = OpenCodeGoAuthLoader(path=p)
        assert loader.get_key() is None

    def test_caches_key_within_ttl(self, auth_file: Path) -> None:
        loader = OpenCodeGoAuthLoader(path=auth_file)
        key1 = loader.get_key()
        # Modify the file but don't change mtime — cache should still be fresh
        # within TTL (we only re-read if TTL expired OR mtime changed)
        auth_file.write_text(
            json.dumps({"opencode-go": {"type": "api", "key": "sk-changed"}}),
            encoding="utf-8",
        )
        # Reset mtime to the original to simulate no-change detection
        import os

        os.utime(auth_file, (time.time(), time.time()))
        key2 = loader.get_key()
        # Key should be cached (same value) because we haven't forced refresh
        # and the mtime check happens after the freshness check
        assert key2 == key1

    def test_force_refresh_picks_up_new_key(self, auth_file: Path) -> None:
        loader = OpenCodeGoAuthLoader(path=auth_file)
        loader.get_key()
        auth_file.write_text(
            json.dumps({"opencode-go": {"type": "api", "key": "sk-rotated"}}),
            encoding="utf-8",
        )
        key = loader.get_key(force_refresh=True)
        assert key == "sk-rotated"


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------


class TestGetOpenCodeGoKey:
    def teardown_method(self) -> None:
        reset_auth_loader()

    def test_module_accessor_uses_default_path(self, auth_file: Path) -> None:
        with patch("copium.opencode_go._DEFAULT_AUTH_PATH", auth_file):
            reset_auth_loader()
            key = get_opencode_go_key()
            assert key == "sk-go-test-key-12345"

    def test_module_accessor_returns_none_when_unconfigured(self, tmp_path: Path) -> None:
        with patch("copium.opencode_go._DEFAULT_AUTH_PATH", tmp_path / "nope.json"):
            reset_auth_loader()
            assert get_opencode_go_key() is None


# ---------------------------------------------------------------------------
# Proxy dispatch logic
# ---------------------------------------------------------------------------


class TestResolveOpenAIUpstream:
    """Test the per-model dispatch in the OpenAI handler mixin."""

    @pytest.fixture()
    def fake_proxy(self):
        from copium.proxy.handlers.openai import OpenAIHandlerMixin

        class FakeProxy(OpenAIHandlerMixin):
            OPENAI_API_URL = "https://api.openai.com"
            OPENCODE_GO_API_URL = "https://opencode.ai/zen/go"

        return FakeProxy()

    def test_go_model_routes_to_go_upstream(self, fake_proxy, auth_file: Path) -> None:
        with patch("copium.opencode_go._DEFAULT_AUTH_PATH", auth_file):
            reset_auth_loader()
            base, headers = fake_proxy._resolve_openai_upstream(
                "glm-5.2", {"content-type": "application/json"}
            )
        assert base == "https://opencode.ai/zen/go"
        assert headers["Authorization"].startswith("Bearer sk-go-test-key")

    def test_non_go_model_routes_to_openai(self, fake_proxy) -> None:
        base, headers = fake_proxy._resolve_openai_upstream(
            "gpt-4o", {"content-type": "application/json"}
        )
        assert base == "https://api.openai.com"
        assert "Authorization" not in headers

    def test_go_model_strips_x_api_key(self, fake_proxy, auth_file: Path) -> None:
        with patch("copium.opencode_go._DEFAULT_AUTH_PATH", auth_file):
            reset_auth_loader()
            _, headers = fake_proxy._resolve_openai_upstream(
                "kimi-k2.7-code", {"x-api-key": "should-be-removed", "Authorization": "old"}
            )
        assert "x-api-key" not in headers
        assert headers["Authorization"].startswith("Bearer sk-go-test-key")

    def test_go_model_without_key_falls_back(
        self, fake_proxy, tmp_path: Path
    ) -> None:
        """When no Go key is configured, fall back to OpenAI upstream."""
        with patch("copium.opencode_go._DEFAULT_AUTH_PATH", tmp_path / "nope.json"):
            reset_auth_loader()
            base, headers = fake_proxy._resolve_openai_upstream(
                "glm-5.2", {"content-type": "application/json"}
            )
        assert base == "https://api.openai.com"
        assert "Authorization" not in headers

    def test_does_not_mutate_input_headers(self, fake_proxy, auth_file: Path) -> None:
        """The helper must not mutate the caller's headers dict."""
        with patch("copium.opencode_go._DEFAULT_AUTH_PATH", auth_file):
            reset_auth_loader()
            original = {"content-type": "application/json", "x-api-key": "keep-me"}
            fake_proxy._resolve_openai_upstream("glm-5.2", original)
        assert original == {"content-type": "application/json", "x-api-key": "keep-me"}
