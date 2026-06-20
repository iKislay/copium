"""Tests for proxy telemetry environment variable handling."""

from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from copium.proxy.server import ProxyConfig, create_app


class TestProxyTelemetrySDKEnv:
    """Test COPIUM_SDK handling when the proxy builds telemetry beacons."""

    def test_proxy_telemetry_sdk_defaults_to_proxy(self, monkeypatch):
        """Telemetry beacon uses the default SDK label when env var is unset."""
        monkeypatch.delenv("COPIUM_SDK", raising=False)

        with patch("copium.telemetry.beacon.TelemetryBeacon") as mock_beacon:
            create_app(
                ProxyConfig(
                    cache_enabled=False,
                    rate_limit_enabled=False,
                    cost_tracking_enabled=False,
                )
            )

        assert mock_beacon.call_args.kwargs["sdk"] == "proxy"

    def test_proxy_telemetry_sdk_uses_env_override(self, monkeypatch):
        """Telemetry beacon uses COPIUM_SDK when it is non-empty."""
        monkeypatch.setenv("COPIUM_SDK", "copium-app")

        with patch("copium.telemetry.beacon.TelemetryBeacon") as mock_beacon:
            create_app(
                ProxyConfig(
                    cache_enabled=False,
                    rate_limit_enabled=False,
                    cost_tracking_enabled=False,
                )
            )

        assert mock_beacon.call_args.kwargs["sdk"] == "copium-app"

    def test_proxy_telemetry_sdk_empty_env_falls_back_to_proxy(self, monkeypatch):
        """Telemetry beacon falls back to proxy when COPIUM_SDK is blank."""
        monkeypatch.setenv("COPIUM_SDK", "   ")

        with patch("copium.telemetry.beacon.TelemetryBeacon") as mock_beacon:
            create_app(
                ProxyConfig(
                    cache_enabled=False,
                    rate_limit_enabled=False,
                    cost_tracking_enabled=False,
                )
            )

        assert mock_beacon.call_args.kwargs["sdk"] == "proxy"
