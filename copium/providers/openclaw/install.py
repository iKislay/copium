"""OpenClaw install-time helpers."""

from __future__ import annotations

import click

from copium.install.models import DeploymentManifest, ManagedMutation, ToolTarget
from copium.install.paths import openclaw_config_path
from copium.install.runtime import resolve_copium_command


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _invoke_openclaw(command: list[str]) -> None:
    import subprocess

    subprocess.run(command, check=True)


def apply_provider_scope(manifest: DeploymentManifest) -> ManagedMutation:
    """Configure OpenClaw to route through the persistent proxy."""
    if not shutil_which("openclaw"):
        raise click.ClickException("openclaw not found in PATH; cannot apply provider scope.")
    command = [
        *resolve_copium_command(),
        "wrap",
        "openclaw",
        "--no-auto-start",
        "--proxy-port",
        str(manifest.port),
    ]
    _invoke_openclaw(command)
    return ManagedMutation(
        target=ToolTarget.OPENCLAW.value,
        kind="openclaw-wrap",
        path=str(openclaw_config_path()),
    )


def revert_provider_scope(mutation: ManagedMutation, manifest: DeploymentManifest) -> None:
    """Undo OpenClaw persistent proxy configuration."""
    del mutation, manifest
    if not shutil_which("openclaw"):
        return
    command = [*resolve_copium_command(), "unwrap", "openclaw"]
    _invoke_openclaw(command)
