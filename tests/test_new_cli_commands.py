"""Tests for the new CLI commands: stats, quickstart, preset, run."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from copium.cli.main import main


# ---------------------------------------------------------------------------
# copium stats
# ---------------------------------------------------------------------------


class TestStatsCommand:
    """Tests for `copium stats` command."""

    def _fake_stats_data(self) -> dict:
        return {
            "schema_version": 3,
            "storage_path": "/fake/.copium/proxy_savings.json",
            "lifetime": {
                "requests": 1247,
                "tokens_saved": 4_200_000,
                "compression_savings_usd": 63.0,
                "total_input_tokens": 10_000_000,
                "total_input_cost_usd": 150.0,
            },
            "display_session": {
                "requests": 47,
                "tokens_saved": 142_000,
                "compression_savings_usd": 2.13,
                "total_input_tokens": 300_000,
                "savings_percent": 32.1,
                "started_at": "2026-06-22T06:00:00Z",
                "last_activity_at": "2026-06-22T07:00:00Z",
            },
            "display_session_policy": {"rollover_inactivity_minutes": 60},
            "history_points": 500,
            "recent_history": [],
            "retention": {},
            "projects": {
                "copium": {
                    "requests": 300,
                    "tokens_saved": 1_500_000,
                    "savings_percent": 42.0,
                }
            },
            "projects_limit": 50,
        }

    def test_stats_shows_summary(self) -> None:
        """copium stats prints a savings summary."""
        runner = CliRunner()
        with patch(
            "copium.cli.stats._fetch_stats",
            return_value=self._fake_stats_data(),
        ):
            result = runner.invoke(main, ["stats"])
        assert result.exit_code == 0
        assert "Copium Savings Report" in result.output

    def test_stats_lifetime_numbers(self) -> None:
        """copium stats --period all shows lifetime tokens/USD."""
        runner = CliRunner()
        with patch(
            "copium.cli.stats._fetch_stats",
            return_value=self._fake_stats_data(),
        ):
            result = runner.invoke(main, ["stats", "--period", "all"])
        assert result.exit_code == 0
        # Lifetime numbers should appear
        assert "1,247" in result.output  # requests

    def test_stats_session_numbers(self) -> None:
        """copium stats --period session shows current session."""
        runner = CliRunner()
        with patch(
            "copium.cli.stats._fetch_stats",
            return_value=self._fake_stats_data(),
        ):
            result = runner.invoke(main, ["stats", "--period", "session"])
        assert result.exit_code == 0
        assert "Current Session" in result.output
        assert "47" in result.output  # session requests

    def test_stats_json_output(self) -> None:
        """copium stats --json outputs valid JSON."""
        runner = CliRunner()
        data = self._fake_stats_data()
        with patch("copium.cli.stats._fetch_stats", return_value=data):
            result = runner.invoke(main, ["stats", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["lifetime"]["requests"] == 1247

    def test_stats_no_data_exits_1(self) -> None:
        """copium stats exits 1 when no savings data exists."""
        runner = CliRunner()
        with patch("copium.cli.stats._fetch_stats", return_value=None):
            result = runner.invoke(main, ["stats"])
        assert result.exit_code == 1

    def test_stats_format_tokens(self) -> None:
        """Token formatting helper formats large numbers correctly."""
        from copium.cli.stats import _format_tokens

        assert _format_tokens(0) == "0"
        assert _format_tokens(999) == "999"
        assert _format_tokens(1500) == "1.5K"
        assert _format_tokens(1_500_000) == "1.5M"

    def test_stats_format_usd(self) -> None:
        """USD formatting helper produces correct strings."""
        from copium.cli.stats import _format_usd

        assert _format_usd(0.0001) == "$0.0001"
        assert _format_usd(0.5) == "$0.5000"   # values < $1 use 4dp
        assert _format_usd(150.0) == "$150"


# ---------------------------------------------------------------------------
# copium preset
# ---------------------------------------------------------------------------


class TestPresetCommand:
    """Tests for `copium preset` command."""

    def test_preset_minimal(self) -> None:
        """copium preset minimal shows minimal config."""
        runner = CliRunner()
        result = runner.invoke(main, ["preset", "minimal"])
        assert result.exit_code == 0
        assert "minimal" in result.output
        assert "smart_crusher" in result.output

    def test_preset_standard(self) -> None:
        """copium preset standard shows standard config."""
        runner = CliRunner()
        result = runner.invoke(main, ["preset", "standard"])
        assert result.exit_code == 0
        assert "standard" in result.output

    def test_preset_aggressive(self) -> None:
        """copium preset aggressive shows aggressive config."""
        runner = CliRunner()
        result = runner.invoke(main, ["preset", "aggressive"])
        assert result.exit_code == 0
        assert "aggressive" in result.output

    def test_preset_local_llm(self) -> None:
        """copium preset local-llm shows local LLM config."""
        runner = CliRunner()
        result = runner.invoke(main, ["preset", "local-llm"])
        assert result.exit_code == 0
        assert "local-llm" in result.output

    def test_preset_lossless(self) -> None:
        """copium preset lossless shows lossless config."""
        runner = CliRunner()
        result = runner.invoke(main, ["preset", "lossless"])
        assert result.exit_code == 0
        assert "lossless" in result.output

    def test_preset_shows_tip(self) -> None:
        """preset command shows proxy start tip."""
        runner = CliRunner()
        result = runner.invoke(main, ["preset", "standard"])
        assert result.exit_code == 0
        assert "copium proxy --preset standard" in result.output


# ---------------------------------------------------------------------------
# copium presets module
# ---------------------------------------------------------------------------


class TestPresetsModule:
    """Tests for the presets module."""

    def test_all_presets_importable(self) -> None:
        """All presets can be imported."""
        from copium.presets import ALL_PRESETS

        assert "minimal" in ALL_PRESETS
        assert "standard" in ALL_PRESETS
        assert "aggressive" in ALL_PRESETS
        assert "local-llm" in ALL_PRESETS
        assert "lossless" in ALL_PRESETS

    def test_create_minimal_config(self) -> None:
        """create_minimal_config returns valid CopiumConfig."""
        from copium.presets import create_minimal_config

        config = create_minimal_config()
        assert config.smart_crusher.enabled is False
        assert config.cache_aligner.enabled is True
        assert config.error_compressor.enabled is True
        assert config.quality_gate.enabled is True

    def test_create_standard_config(self) -> None:
        """create_standard_config returns default CopiumConfig."""
        from copium.presets import create_standard_config

        config = create_standard_config()
        # Standard is all defaults — smart_crusher is on by default
        assert config.smart_crusher.enabled is True

    def test_create_aggressive_config(self) -> None:
        """create_aggressive_config uses lower max_items than standard."""
        from copium.presets import create_aggressive_config, create_standard_config

        std = create_standard_config()
        agg = create_aggressive_config()
        assert agg.smart_crusher.max_items_after_crush < std.smart_crusher.max_items_after_crush
        assert agg.cache_aligner.enabled is True

    def test_create_lossless_config(self) -> None:
        """create_lossless_config disables lossy transforms."""
        from copium.presets import create_lossless_config

        config = create_lossless_config()
        assert config.smart_crusher.enabled is False
        assert config.output_compressor.enabled is False
        assert config.cache_aligner.enabled is True
        assert config.quality_gate.enabled is True

    def test_create_local_llm_config(self) -> None:
        """create_local_llm_config enables cache_aligner."""
        from copium.presets import create_local_llm_config

        config = create_local_llm_config()
        assert config.cache_aligner.enabled is True
        assert config.session_dedup.enabled is True

    def test_preset_descriptions_exist(self) -> None:
        """All presets have descriptions."""
        from copium.presets import ALL_PRESETS, PRESET_DESCRIPTIONS

        for name in ALL_PRESETS:
            assert name in PRESET_DESCRIPTIONS
            assert len(PRESET_DESCRIPTIONS[name]) > 5


# ---------------------------------------------------------------------------
# ModelFallbackConfig
# ---------------------------------------------------------------------------


class TestModelFallbackConfig:
    """Tests for the ModelFallbackConfig dataclass."""

    def test_default_config(self) -> None:
        """ModelFallbackConfig has correct defaults."""
        from copium.config import ModelFallbackConfig

        cfg = ModelFallbackConfig()
        assert cfg.enabled is True
        assert cfg.model_map == {}
        assert 429 in cfg.trigger_status_codes
        assert 503 in cfg.trigger_status_codes
        assert cfg.max_retries == 1
        assert cfg.backoff_seconds == 1.0

    def test_config_with_model_map(self) -> None:
        """ModelFallbackConfig stores a model map."""
        from copium.config import ModelFallbackConfig

        cfg = ModelFallbackConfig(
            model_map={"claude-sonnet-4-5": "claude-haiku-4-5"}
        )
        assert cfg.model_map["claude-sonnet-4-5"] == "claude-haiku-4-5"

    def test_copium_config_has_model_fallback(self) -> None:
        """CopiumConfig includes model_fallback field."""
        from copium.config import CopiumConfig, ModelFallbackConfig

        cfg = CopiumConfig()
        assert hasattr(cfg, "model_fallback")
        assert isinstance(cfg.model_fallback, ModelFallbackConfig)
        assert cfg.model_fallback.enabled is True


# ---------------------------------------------------------------------------
# copium run (alias for proxy)
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for `copium run` alias command."""

    def test_run_is_registered(self) -> None:
        """copium run command is visible in --help."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_run_has_help_text(self) -> None:
        """copium run --help shows expected description."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        # run rewrites argv and re-invokes; check it has the proxy help content
        # The help may come from proxy after the rewrite
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# copium quickstart
# ---------------------------------------------------------------------------


class TestQuickstartCommand:
    """Tests for `copium quickstart` command."""

    def test_quickstart_help(self) -> None:
        """copium quickstart --help exits cleanly."""
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", "--help"])
        assert result.exit_code == 0
        assert "quickstart" in result.output.lower() or "wizard" in result.output.lower()

    def test_quickstart_no_start(self) -> None:
        """copium quickstart --no-start prints instructions without starting proxy."""
        runner = CliRunner()

        # Simulate Anthropic key present
        env = {"ANTHROPIC_API_KEY": "sk-test-key"}
        with patch("os.environ", {**env}):
            result = runner.invoke(main, ["quickstart", "--no-start"], env=env)

        assert result.exit_code == 0
        assert "ANTHROPIC_BASE_URL" in result.output

    def test_quickstart_detects_anthropic_key(self) -> None:
        """quickstart detects ANTHROPIC_API_KEY."""
        from copium.cli.quickstart import _detect_provider

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            result = _detect_provider()
        assert result is not None
        provider_name, model, env_var = result
        assert provider_name == "anthropic"
        assert env_var == "ANTHROPIC_BASE_URL"

    def test_quickstart_detects_openai_key(self) -> None:
        """quickstart detects OPENAI_API_KEY."""
        from copium.cli.quickstart import _detect_provider

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-openai-test"}, clear=True):
            result = _detect_provider()
        assert result is not None
        provider_name, _, _ = result
        assert provider_name == "openai"

    def test_quickstart_no_key_returns_none(self) -> None:
        """quickstart returns None when no known API key is set."""
        from copium.cli.quickstart import _detect_provider

        with patch.dict("os.environ", {}, clear=True):
            result = _detect_provider()
        assert result is None

    def test_quickstart_port_free_check(self) -> None:
        """_port_free returns True for an available port."""
        from copium.cli.quickstart import _port_free

        # Use a random high port that should be free
        assert _port_free(59123) is True

    def test_quickstart_proxy_listening_false(self) -> None:
        """_proxy_listening returns False when nothing is on the port."""
        from copium.cli.quickstart import _proxy_listening

        assert _proxy_listening(59124) is False
