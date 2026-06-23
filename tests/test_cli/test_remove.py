"""Tests for copium remove command.

Plan §3b: clean uninstall.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from copium.cli.main import main


def test_remove_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["remove", "--help"])

    assert result.exit_code == 0, result.output
    assert "Fully remove Copium" in result.output


def test_remove_with_no_config() -> None:
    runner = CliRunner()
    with patch("copium.cli.remove._remove_copium_from_shell_rc_files", return_value=[]):
        with patch("copium.cli.remove._remove_global_config", return_value=False):
            with patch("copium.cli.remove._remove_deployment_profiles", return_value=[]):
                with patch("copium.cli.remove.Path.home") as home_mock:
                    home_mock.return_value = Path("/tmp/nonexistent")
                    result = runner.invoke(main, ["remove", "--force"])

    assert result.exit_code == 0, result.output
    assert "No Copium configuration found" in result.output


def test_remove_cleans_shell_rc() -> None:
    runner = CliRunner()
    with patch("copium.cli.remove._remove_copium_from_shell_rc_files", return_value=[Path("/home/user/.zshrc")]):
        with patch("copium.cli.remove._remove_global_config", return_value=False):
            with patch("copium.cli.remove._remove_deployment_profiles", return_value=[]):
                with patch("copium.cli.remove.Path.home") as home_mock:
                    home_mock.return_value = Path("/tmp/nonexistent")
                    result = runner.invoke(main, ["remove", "--force"])

    assert result.exit_code == 0, result.output
    assert "Cleaned" in result.output
    assert ".zshrc" in result.output


def test_remove_with_force_skips_confirmation() -> None:
    runner = CliRunner()
    with patch("copium.cli.remove._remove_copium_from_shell_rc_files", return_value=[]):
        with patch("copium.cli.remove._remove_global_config", return_value=False):
            with patch("copium.cli.remove._remove_deployment_profiles", return_value=[]):
                with patch("copium.cli.remove.Path.home") as home_mock:
                    home_mock.return_value = Path("/tmp/nonexistent")
                    result = runner.invoke(main, ["remove", "--force"], input="n\n")

    assert result.exit_code == 0, result.output


def test_remove_removes_global_config() -> None:
    runner = CliRunner()
    with patch("copium.cli.remove._remove_copium_from_shell_rc_files", return_value=[]):
        with patch("copium.cli.remove._remove_global_config", return_value=True):
            with patch("copium.cli.remove._remove_deployment_profiles", return_value=[]):
                with patch("copium.cli.remove.Path.home") as home_mock:
                    home_mock.return_value = Path("/tmp/nonexistent")
                    result = runner.invoke(main, ["remove", "--force"])

    assert result.exit_code == 0, result.output
    assert "Removed global config" in result.output


def test_remove_with_deployment_profiles() -> None:
    runner = CliRunner()
    with patch("copium.cli.remove._remove_copium_from_shell_rc_files", return_value=[]):
        with patch("copium.cli.remove._remove_global_config", return_value=False):
            with patch("copium.cli.remove._remove_deployment_profiles", return_value=["init-user"]):
                with patch("copium.cli.remove.Path.home") as home_mock:
                    home_mock.return_value = Path("/tmp/nonexistent")
                    result = runner.invoke(main, ["remove", "--force"])

    assert result.exit_code == 0, result.output
    assert "init-user" in result.output


def test_remove_removes_copium_directory_with_confirmation() -> None:
    runner = CliRunner()
    with patch("copium.cli.remove._remove_copium_from_shell_rc_files", return_value=[]):
        with patch("copium.cli.remove._remove_global_config", return_value=False):
            with patch("copium.cli.remove._remove_deployment_profiles", return_value=[]):
                with patch("copium.cli.remove.Path.home") as home_mock:
                    copium_dir = Path("/tmp/test-copium-dir")
                    copium_dir.mkdir(parents=True, exist_ok=True)
                    home_mock.return_value = copium_dir.parent
                    result = runner.invoke(main, ["remove"], input="y\n")

    assert result.exit_code == 0, result.output
