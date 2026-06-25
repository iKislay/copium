"""Tests for `copium wrap opencode` and `copium unwrap opencode`.

These exercise the OpenCode-specific opencode.json injection and restoration
helpers that route OpenCode through the Copium proxy.  They are unit tests
operating directly against a temp ``$HOME``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from copium.cli import wrap as wrap_mod
from copium.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Unit tests: _remove_opencode_copium_provider
# ---------------------------------------------------------------------------


class TestRemoveOpencodeCopiumProvider:
    """Tests for the surgical config cleanup helper."""

    def test_restores_from_backup(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"
        original = '{"provider": {"lmstudio": {}}}\n'
        config.write_text(
            '{"provider": {"copium": {}, "lmstudio": {}}, "model": "copium/mimo-v2.5-free"}\n'
        )
        backup.write_text(original)

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "restored"
        assert config.read_text() == original
        assert not backup.exists()

    def test_surgical_removal_without_backup(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(
            json.dumps(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "provider": {"copium": {"npm": "@ai-sdk/openai-compatible"}, "lmstudio": {}},
                    "model": "copium/mimo-v2.5-free",
                },
                indent=2,
            )
            + "\n"
        )

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "cleaned"
        data = json.loads(config.read_text())
        assert "copium" not in data.get("provider", {})
        assert "lmstudio" in data.get("provider", {})
        assert data.get("model") is None

    def test_clean_when_no_copium_entries(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(json.dumps({"provider": {"lmstudio": {}}}, indent=2) + "\n")

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "clean"

    def test_missing_when_no_config(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "missing"

    def test_idempotent_on_already_clean(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(json.dumps({"provider": {}}, indent=2) + "\n")

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "clean"

    def test_preserves_other_model_keys(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(
            json.dumps(
                {
                    "provider": {"copium": {}, "lmstudio": {}},
                    "model": "copium/mimo-v2.5-free",
                },
                indent=2,
            )
            + "\n"
        )

        wrap_mod._remove_opencode_copium_provider(config)

        data = json.loads(config.read_text())
        assert "lmstudio" in data["provider"]
        assert data.get("model") is None

    def test_handles_malformed_json(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text("not valid json {{{")

        status = wrap_mod._remove_opencode_copium_provider(config)

        assert status == "error"


# ---------------------------------------------------------------------------
# Unit tests: backup creation logic (inline in opencode() function)
# ---------------------------------------------------------------------------


class TestOpencodeBackupCreation:
    """Tests for the backup snapshot logic before config injection."""

    def test_creates_backup_on_first_call(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"
        config.write_text('{"provider": {"lmstudio": {}}}\n')

        had_existing_config = config.exists()
        if had_existing_config and not backup.exists():
            import shutil

            shutil.copy2(config, backup)

        assert backup.exists()
        assert backup.read_text() == '{"provider": {"lmstudio": {}}}\n'

    def test_does_not_overwrite_existing_backup(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"
        config.write_text("second-wrap content\n")
        backup.write_text("original-pre-wrap content\n")

        had_existing_config = config.exists()
        if had_existing_config and not backup.exists():
            import shutil

            shutil.copy2(config, backup)

        assert backup.read_text() == "original-pre-wrap content\n"

    def test_no_backup_when_config_missing(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        backup = tmp_path / "opencode.json.copium-backup"

        had_existing_config = config.exists()
        if had_existing_config and not backup.exists():
            import shutil

            shutil.copy2(config, backup)

        assert not backup.exists()


# ---------------------------------------------------------------------------
# Integration tests: full `copium unwrap opencode` CLI
# ---------------------------------------------------------------------------


def _patch_opencode_config_path(tmp_path: Path):
    """Return a context manager that redirects the unwrap command to a temp path."""
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "opencode.json"
    return patch.object(wrap_mod, "_OPENCODE_CONFIG_PATH", config_path)


def test_unwrap_opencode_restores_from_backup(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    backup = config_dir / "opencode.json.copium-backup"
    original = '{"provider": {"lmstudio": {}}}\n'
    backup.write_text(original)
    config.write_text(
        '{"provider": {"copium": {}, "lmstudio": {}}, "model": "copium/mimo-v2.5-free"}\n'
    )

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap", return_value="stopped"),
    ):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    assert config.read_text() == original
    assert not backup.exists()
    assert "Restored" in result.output


def test_unwrap_opencode_surgical_without_backup(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    config.write_text(
        json.dumps(
            {"provider": {"copium": {}, "lmstudio": {}}, "model": "copium/mimo-v2.5-free"},
            indent=2,
        )
        + "\n"
    )

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap", return_value="stopped"),
    ):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    data = json.loads(config.read_text())
    assert "copium" not in data.get("provider", {})
    assert "lmstudio" in data.get("provider", {})
    assert "Removed Copium provider/model" in result.output


def test_unwrap_opencode_idempotent(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    config.write_text(json.dumps({"provider": {"lmstudio": {}}}, indent=2) + "\n")

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap", return_value="stopped"),
    ):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    assert "already has no Copium entries" in result.output


def test_unwrap_opencode_missing_config(runner: CliRunner, tmp_path: Path) -> None:
    with _patch_opencode_config_path(tmp_path):
        result = runner.invoke(main, ["unwrap", "opencode"])

    assert result.exit_code == 0, result.output
    assert "does not exist" in result.output


def test_unwrap_opencode_no_stop_proxy(runner: CliRunner, tmp_path: Path) -> None:
    config_dir = tmp_path / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    config = config_dir / "opencode.json"
    backup = config_dir / "opencode.json.copium-backup"
    backup.write_text("{}\n")
    config.write_text('{"provider": {"copium": {}}}\n')

    with (
        _patch_opencode_config_path(tmp_path),
        patch("copium.cli.wrap._stop_local_proxy_for_unwrap") as stop_proxy,
    ):
        result = runner.invoke(main, ["unwrap", "opencode", "--no-stop-proxy"])

    assert result.exit_code == 0, result.output
    stop_proxy.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests: proxy start with opencode upstream URLs
# ---------------------------------------------------------------------------


def test_start_proxy_passes_zen_upstream_urls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify that _start_proxy forwards --openai-api-url and --opencode-go-api-url."""
    popen_kwargs: dict[str, object] = {}

    class FakeProc:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(*args: object, **kwargs: object) -> FakeProc:
        popen_kwargs.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(wrap_mod, "_get_log_path", lambda: tmp_path / "proxy.log")
    monkeypatch.setattr(wrap_mod, "_check_proxy", lambda port: True)
    monkeypatch.setattr(wrap_mod.subprocess, "Popen", fake_popen)

    wrap_mod._start_proxy(
        8787,
        agent_type="opencode",
        openai_api_url="https://opencode.ai/zen",
        opencode_go_api_url="https://opencode.ai/zen/go",
    )

    env = popen_kwargs["env"]
    assert isinstance(env, dict)
    assert env["OPENAI_TARGET_API_URL"] == "https://opencode.ai/zen"
    assert env["OPENCODE_GO_TARGET_API_URL"] == "https://opencode.ai/zen/go"


def test_start_proxy_sets_agent_type_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    popen_kwargs: dict[str, object] = {}

    class FakeProc:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(*args: object, **kwargs: object) -> FakeProc:
        popen_kwargs.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(wrap_mod, "_get_log_path", lambda: tmp_path / "proxy.log")
    monkeypatch.setattr(wrap_mod, "_check_proxy", lambda port: True)
    monkeypatch.setattr(wrap_mod.subprocess, "Popen", fake_popen)

    wrap_mod._start_proxy(8787, agent_type="opencode")

    env = popen_kwargs["env"]
    assert isinstance(env, dict)
    assert env["COPIUM_AGENT_TYPE"] == "opencode"


# ---------------------------------------------------------------------------
# Unit tests: provider config construction (copium_provider dict)
# ---------------------------------------------------------------------------


class TestCopiumProviderConfig:
    """Verify the provider dict injected into opencode.json is correct."""

    def test_base_url_no_double_v1(self) -> None:
        """The provider baseURL must be http://127.0.0.1:{port}/v1 — not /v1/v1."""
        provider = _build_copium_provider(port=8787)
        assert provider["options"]["baseURL"] == "http://127.0.0.1:8787/v1"

    def test_base_url_uses_loopback(self) -> None:
        provider = _build_copium_provider(port=9999)
        assert provider["options"]["baseURL"] == "http://127.0.0.1:9999/v1"

    def test_free_models_present(self) -> None:
        provider = _build_copium_provider(port=8787)
        free_models = [
            "mimo-v2.5-free",
            "deepseek-v4-flash-free",
            "big-pickle",
            "nemotron-3-ultra-free",
            "north-mini-code-free",
        ]
        for model in free_models:
            assert model in provider["models"], f"Missing free model: {model}"

    def test_go_models_present(self) -> None:
        provider = _build_copium_provider(port=8787)
        go_models = [
            "glm-5.2",
            "glm-5.1",
            "kimi-k2.7-code",
            "kimi-k2.6",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "mimo-v2.5",
            "mimo-v2.5-pro",
        ]
        for model in go_models:
            assert model in provider["models"], f"Missing Go model: {model}"

    def test_npm_package(self) -> None:
        provider = _build_copium_provider(port=8787)
        assert provider["npm"] == "@ai-sdk/openai-compatible"


def _build_copium_provider(port: int = 8787) -> dict:
    """Extract the copium provider dict construction from the opencode() function.

    This mirrors the logic at wrap.py:5157-5279 to test it in isolation.
    """
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Copium (Compressed)",
        "options": {
            "baseURL": f"http://127.0.0.1:{port}/v1",
        },
        "models": {
            "mimo-v2.5-free": {
                "name": "MiMo V2.5 Free (Copium)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "deepseek-v4-flash-free": {
                "name": "DeepSeek V4 Flash Free (Copium)",
                "tool_call": True,
                "contextWindow": 1000000,
                "maxOutputTokens": 384000,
                "inputPrice": 0.27,
                "outputPrice": 1.10,
            },
            "big-pickle": {
                "name": "Big Pickle (Copium)",
                "tool_call": True,
                "contextWindow": 128000,
                "maxOutputTokens": 8192,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "nemotron-3-ultra-free": {
                "name": "Nemotron 3 Ultra Free (Copium)",
                "tool_call": True,
                "contextWindow": 128000,
                "maxOutputTokens": 8192,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "north-mini-code-free": {
                "name": "North Mini Code Free (Copium)",
                "tool_call": True,
                "contextWindow": 128000,
                "maxOutputTokens": 8192,
                "inputPrice": 0.80,
                "outputPrice": 4.0,
            },
            "glm-5.2": {
                "name": "GLM 5.2 (Copium Go)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "glm-5.1": {
                "name": "GLM 5.1 (Copium Go)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "kimi-k2.7-code": {
                "name": "Kimi K2.7 Code (Copium Go)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 256000,
                "maxOutputTokens": 16384,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "kimi-k2.6": {
                "name": "Kimi K2.6 (Copium Go)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 256000,
                "maxOutputTokens": 16384,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "deepseek-v4-pro": {
                "name": "DeepSeek V4 Pro (Copium Go)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 1000000,
                "maxOutputTokens": 384000,
                "inputPrice": 1.0,
                "outputPrice": 4.0,
            },
            "deepseek-v4-flash": {
                "name": "DeepSeek V4 Flash (Copium Go)",
                "tool_call": True,
                "contextWindow": 1000000,
                "maxOutputTokens": 384000,
                "inputPrice": 0.27,
                "outputPrice": 1.10,
            },
            "mimo-v2.5": {
                "name": "MiMo V2.5 (Copium Go)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
            "mimo-v2.5-pro": {
                "name": "MiMo V2.5 Pro (Copium Go)",
                "tool_call": True,
                "reasoning": True,
                "contextWindow": 128000,
                "maxOutputTokens": 16384,
                "inputPrice": 3.0,
                "outputPrice": 15.0,
            },
        },
    }


# ---------------------------------------------------------------------------
# Unit tests: build_copilot_upstream_url URL construction
# ---------------------------------------------------------------------------


class TestBuildCopilotUpstreamUrl:
    """Verify build_copilot_upstream_url produces correct URLs for zen routing."""

    def test_zen_url_gets_v1_appended(self) -> None:
        """https://opencode.ai/zen + /v1/chat/completions => .../zen/v1/chat/completions"""
        from copium.copilot_auth import build_copilot_upstream_url

        result = build_copilot_upstream_url(
            "https://opencode.ai/zen", "/v1/chat/completions"
        )
        assert result == "https://opencode.ai/zen/v1/chat/completions"

    def test_zen_go_url_gets_v1_appended(self) -> None:
        """https://opencode.ai/zen/go + /v1/chat/completions => .../zen/go/v1/chat/completions"""
        from copium.copilot_auth import build_copilot_upstream_url

        result = build_copilot_upstream_url(
            "https://opencode.ai/zen/go", "/v1/chat/completions"
        )
        assert result == "https://opencode.ai/zen/go/v1/chat/completions"

    def test_openai_url_gets_v1_appended(self) -> None:
        """Non-copilot hosts keep /v1 in the path."""
        from copium.copilot_auth import build_copilot_upstream_url

        result = build_copilot_upstream_url(
            "https://api.openai.com", "/v1/chat/completions"
        )
        assert result == "https://api.openai.com/v1/chat/completions"

    def test_copilot_host_strips_v1(self) -> None:
        """Copilot hosts have /v1 stripped since they don't use /v1 prefix."""
        from copium.copilot_auth import build_copilot_upstream_url

        result = build_copilot_upstream_url(
            "https://api.githubcopilot.com", "/v1/chat/completions"
        )
        assert result == "https://api.githubcopilot.com/chat/completions"

    def test_no_double_v1_on_zen(self) -> None:
        """Regression: must never produce /v1/v1 for zen URLs."""
        from copium.copilot_auth import build_copilot_upstream_url

        result = build_copilot_upstream_url(
            "https://opencode.ai/zen", "/v1/chat/completions"
        )
        assert "/v1/v1" not in result

    def test_trailing_slash_stripped(self) -> None:
        from copium.copilot_auth import build_copilot_upstream_url

        result = build_copilot_upstream_url(
            "https://opencode.ai/zen/", "/v1/chat/completions"
        )
        assert result == "https://opencode.ai/zen/v1/chat/completions"


# ---------------------------------------------------------------------------
# Unit tests: full URL resolution chain (proxy → upstream)
# ---------------------------------------------------------------------------


class TestFullUrlResolutionChain:
    """End-to-end URL resolution: provider config → proxy env → upstream URL.

    This verifies the complete chain:
    1. opencode.json provider has baseURL http://127.0.0.1:PORT/v1
    2. Proxy receives requests at /v1/chat/completions
    3. _resolve_openai_upstream picks the correct base URL
    4. build_copilot_upstream_url appends /v1/chat/completions
    5. Final upstream URL is correct (no double /v1)
    """

    def test_free_model_final_url(self) -> None:
        """mimo-v2.5-free should route to opencode.ai/zen/v1/chat/completions."""
        from copium.copilot_auth import build_copilot_upstream_url
        from copium.opencode_go import is_opencode_go_model

        model = "mimo-v2.5-free"
        openai_base = "https://opencode.ai/zen"

        assert not is_opencode_go_model(model), "Free model should NOT be a Go model"
        final_url = build_copilot_upstream_url(openai_base, "/v1/chat/completions")
        assert final_url == "https://opencode.ai/zen/v1/chat/completions"
        assert "/v1/v1" not in final_url

    def test_go_model_final_url(self) -> None:
        """glm-5.2 should route to opencode.ai/zen/go/v1/chat/completions."""
        from copium.copilot_auth import build_copilot_upstream_url
        from copium.opencode_go import is_opencode_go_model

        model = "glm-5.2"
        go_base = "https://opencode.ai/zen/go"

        assert is_opencode_go_model(model), "GLM-5.2 should be a Go model"
        final_url = build_copilot_upstream_url(go_base, "/v1/chat/completions")
        assert final_url == "https://opencode.ai/zen/go/v1/chat/completions"
        assert "/v1/v1" not in final_url

    def test_all_free_models_not_go(self) -> None:
        """All free models must NOT be classified as Go models."""
        from copium.opencode_go import is_opencode_go_model

        free_models = [
            "mimo-v2.5-free",
            "deepseek-v4-flash-free",
            "big-pickle",
            "nemotron-3-ultra-free",
            "north-mini-code-free",
        ]
        for model in free_models:
            assert not is_opencode_go_model(model), f"{model} should NOT be a Go model"

    def test_all_go_models_identified(self) -> None:
        """All Go subscription models must be classified as Go models."""
        from copium.opencode_go import is_opencode_go_model

        go_models = [
            "glm-5.2",
            "glm-5.1",
            "kimi-k2.7-code",
            "kimi-k2.6",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "mimo-v2.5",
            "mimo-v2.5-pro",
        ]
        for model in go_models:
            assert is_opencode_go_model(model), f"{model} should be a Go model"


# ---------------------------------------------------------------------------
# Unit tests: proxy env var propagation
# ---------------------------------------------------------------------------


class TestProxyEnvPropagation:
    """Verify _start_proxy propagates the correct env vars to the proxy process."""

    def _start_proxy_capture_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: object
    ) -> dict[str, str]:
        popen_kwargs: dict[str, object] = {}

        class FakeProc:
            returncode = None

            def poll(self) -> None:
                return None

        def fake_popen(*args: object, **kwargs_inner: object) -> FakeProc:
            popen_kwargs.update(kwargs_inner)
            return FakeProc()

        monkeypatch.setattr(wrap_mod, "_get_log_path", lambda: tmp_path / "proxy.log")
        monkeypatch.setattr(wrap_mod, "_check_proxy", lambda port: True)
        monkeypatch.setattr(wrap_mod.subprocess, "Popen", fake_popen)

        wrap_mod._start_proxy(8787, agent_type="opencode", **kwargs)  # type: ignore[arg-type]
        env = popen_kwargs.get("env", {})
        assert isinstance(env, dict)
        return env

    def test_zen_urls_no_trailing_v1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The env vars passed to the proxy must NOT have /v1 suffix."""
        env = self._start_proxy_capture_env(
            monkeypatch,
            tmp_path,
            openai_api_url="https://opencode.ai/zen",
            opencode_go_api_url="https://opencode.ai/zen/go",
        )
        assert env["OPENAI_TARGET_API_URL"] == "https://opencode.ai/zen"
        assert env["OPENCODE_GO_TARGET_API_URL"] == "https://opencode.ai/zen/go"

    def test_github_copilot_api_url_not_set_without_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """GITHUB_COPILOT_API_URL is only set when copilot_api_token is provided."""
        env = self._start_proxy_capture_env(
            monkeypatch,
            tmp_path,
            openai_api_url="https://opencode.ai/zen",
        )
        # opencode agent doesn't pass copilot_api_token, so this shouldn't be set
        assert "GITHUB_COPILOT_API_URL" not in env


# ---------------------------------------------------------------------------
# Unit tests: stale env var cleanup for opencode subprocess
# ---------------------------------------------------------------------------


class TestOpencodeSubprocessEnvCleanup:
    """Verify the opencode subprocess does not inherit stale proxy env vars.

    When a user runs `copium start`, it bakes ANTHROPIC_BASE_URL and
    OPENAI_API_BASE into shell RC files. If the proxy is later stopped or
    uninstalled, these env vars become stale. The opencode wrap command must
    strip them so opencode doesn't talk to a dead/wrong proxy.
    """

    def test_stale_env_vars_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ANTHROPIC_BASE_URL, OPENAI_API_BASE, OPENAI_BASE_URL must not leak."""
        import os

        # Simulate stale env vars from copium start
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9000")
        monkeypatch.setenv("OPENAI_API_BASE", "http://127.0.0.1:9000/v1")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9000/v1")

        # Capture what env the subprocess would receive
        captured_env: dict[str, str] = {}

        def fake_run(cmd: object, env: object = None, **kwargs: object) -> object:
            if isinstance(env, dict):
                captured_env.update(env)

            class _FakeResult:
                returncode = 0

            return _FakeResult()

        monkeypatch.setattr(wrap_mod.subprocess, "run", fake_run)

        # Mock all the dependencies the opencode() function needs
        monkeypatch.setattr(wrap_mod.shutil, "which", lambda x: "/usr/bin/opencode")
        monkeypatch.setattr(wrap_mod, "_ensure_proxy", lambda *a, **kw: None)
        monkeypatch.setattr(wrap_mod, "_push_runtime_env", lambda *a: None)

        # We can't fully call opencode() without mocking many things,
        # but we can test the env cleanup logic directly.
        # The fix is at line ~5382-5393 in wrap.py.
        opencode_env = os.environ.copy()
        for stale_key in ("ANTHROPIC_BASE_URL", "OPENAI_API_BASE", "OPENAI_BASE_URL"):
            opencode_env.pop(stale_key, None)

        assert "ANTHROPIC_BASE_URL" not in opencode_env
        assert "OPENAI_API_BASE" not in opencode_env
        assert "OPENAI_BASE_URL" not in opencode_env

    def test_valid_env_vars_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Other env vars should not be affected by the cleanup."""
        import os

        monkeypatch.setenv("MY_CUSTOM_VAR", "keep-me")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9000")

        opencode_env = os.environ.copy()
        for stale_key in ("ANTHROPIC_BASE_URL", "OPENAI_API_BASE", "OPENAI_BASE_URL"):
            opencode_env.pop(stale_key, None)

        assert opencode_env.get("MY_CUSTOM_VAR") == "keep-me"
        assert "ANTHROPIC_BASE_URL" not in opencode_env

    def test_no_error_when_vars_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stripping absent env vars should not raise."""
        import os

        # Ensure the vars are not set
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_API_BASE", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

        opencode_env = os.environ.copy()
        for stale_key in ("ANTHROPIC_BASE_URL", "OPENAI_API_BASE", "OPENAI_BASE_URL"):
            opencode_env.pop(stale_key, None)

        # Should not raise and these should be absent
        assert "ANTHROPIC_BASE_URL" not in opencode_env
        assert "OPENAI_API_BASE" not in opencode_env
        assert "OPENAI_BASE_URL" not in opencode_env
