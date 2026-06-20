from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from copium.install.models import DeploymentManifest, InstallPreset
from copium.install.runtime import (
    _clear_pid,
    _deployment_env,
    _mount_source,
    _read_pid,
    _runtime_env,
    _write_pid,
    acquire_runtime_start_lock,
    build_runtime_command,
    resolve_copium_command,
    run_foreground,
    runtime_status,
    start_detached_agent,
    start_persistent_docker,
    stop_runtime,
    wait_ready,
)


def test_build_runtime_command_for_docker_includes_deployment_env(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    manifest = DeploymentManifest(
        profile="default",
        preset="persistent-docker",
        runtime_kind="docker",
        supervisor_kind="none",
        scope="user",
        provider_mode="manual",
        targets=["claude"],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        image="ghcr.io/iKislay/copium:latest",
        base_env={"COPIUM_PORT": "8787"},
        proxy_args=["--host", "127.0.0.1", "--port", "8787"],
    )

    command = build_runtime_command(manifest)

    joined = " ".join(command)
    assert command[:3] == ["docker", "run", "--rm"]
    assert "COPIUM_DEPLOYMENT_PROFILE=default" in joined
    assert "COPIUM_DEPLOYMENT_PRESET=persistent-docker" in joined
    assert "127.0.0.1:8787:8787" in joined
    assert "ghcr.io/iKislay/copium:latest" in command
    # Canonical Copium filesystem contract (issue #175) forwarded into
    # the container.
    assert "COPIUM_WORKSPACE_DIR=/tmp/copium-home/.copium" in command
    assert "COPIUM_CONFIG_DIR=/tmp/copium-home/.copium/config" in command


def test_build_runtime_command_for_docker_matches_wrapper_parity(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    manifest = DeploymentManifest(
        profile="default",
        preset="persistent-docker",
        runtime_kind="docker",
        supervisor_kind="none",
        scope="user",
        provider_mode="manual",
        targets=["claude"],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        image="ghcr.io/iKislay/copium:latest",
        base_env={"COPIUM_PORT": "8787"},
        proxy_args=["--host", "127.0.0.1", "--port", "8787"],
    )

    command = build_runtime_command(manifest)

    assert (tmp_path / ".copium").is_dir()
    assert (tmp_path / ".claude").is_dir()
    assert (tmp_path / ".codex").is_dir()
    assert (tmp_path / ".gemini").is_dir()
    assert "--env" in command
    joined = " ".join(command)
    assert "ANTHROPIC_API_KEY" in joined
    assert "OPENAI_API_KEY" in joined


def test_resolve_copium_command_prefers_copium_binary(monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/copium" if name == "copium" else None
    )

    assert resolve_copium_command() == ["/usr/bin/copium"]


def test_resolve_copium_command_falls_back_to_python_module(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("copium.install.runtime.sys.executable", "/usr/bin/python")
    assert resolve_copium_command() == ["/usr/bin/python", "-m", "copium.cli"]


def test_runtime_env_and_mount_source(monkeypatch) -> None:
    manifest = DeploymentManifest(
        profile="default",
        preset="persistent-service",
        runtime_kind="python",
        supervisor_kind="service",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        base_env={"EXTRA": "1"},
    )
    monkeypatch.setattr("copium.install.runtime.os.environ", {"BASE": "x"})

    assert _deployment_env(manifest) == {
        "COPIUM_DEPLOYMENT_PROFILE": "default",
        "COPIUM_DEPLOYMENT_PRESET": "persistent-service",
        "COPIUM_DEPLOYMENT_RUNTIME": "python",
        "COPIUM_DEPLOYMENT_SUPERVISOR": "service",
        "COPIUM_DEPLOYMENT_SCOPE": "user",
    }
    assert _runtime_env(manifest)["BASE"] == "x"
    assert _runtime_env(manifest)["EXTRA"] == "1"
    assert _runtime_env(manifest)["COPIUM_DEPLOYMENT_PROFILE"] == "default"

    monkeypatch.setattr("copium.install.runtime.sys.platform", "win32")
    assert _mount_source("C:\\Users\\me", ".copium") == "C:\\Users\\me\\.copium"
    monkeypatch.setattr("copium.install.runtime.sys.platform", "linux")
    assert _mount_source("/home/me", ".copium") == "/home/me/.copium"


def test_build_runtime_command_python_and_docker_user(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("copium.install.runtime.sys.executable", "/usr/bin/python")
    manifest = DeploymentManifest(
        profile="default",
        preset="persistent-service",
        runtime_kind="python",
        supervisor_kind="service",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        proxy_args=["--host", "127.0.0.1", "--port", "8787"],
    )
    assert build_runtime_command(manifest) == [
        "/usr/bin/python",
        "-m",
        "copium.cli",
        "proxy",
        "--host",
        "127.0.0.1",
        "--port",
        "8787",
    ]

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("copium.install.runtime.sys.platform", "linux")
    monkeypatch.setattr("copium.install.runtime.os.getuid", lambda: 1000, raising=False)
    monkeypatch.setattr("copium.install.runtime.os.getgid", lambda: 1001, raising=False)
    docker_manifest = DeploymentManifest(
        profile="default",
        preset="persistent-docker",
        runtime_kind="docker",
        supervisor_kind="none",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        image="ghcr.io/iKislay/copium:latest",
        base_env={"COPIUM_PORT": "8787"},
        proxy_args=["--host", "127.0.0.1", "--port", "8787"],
    )
    command = build_runtime_command(docker_manifest)
    assert "--user" in command
    assert "1000:1001" in command


def test_read_pid_handles_invalid_content(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    pid_file = tmp_path / ".copium" / "deploy" / "default" / "runner.pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("not-a-pid", encoding="utf-8")

    assert _read_pid("default") is None
    _clear_pid("default")
    assert not pid_file.exists()


def test_write_read_and_clear_pid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _write_pid("default", 456)
    assert _read_pid("default") == 456
    _clear_pid("default")
    assert _read_pid("default") is None


def test_runtime_start_lock_is_nonblocking(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with acquire_runtime_start_lock("default") as first_acquired:
        assert first_acquired is True
        with acquire_runtime_start_lock("default") as second_acquired:
            assert second_acquired is False

    with acquire_runtime_start_lock("default") as acquired_after_release:
        assert acquired_after_release is True


def test_runtime_start_lock_blocks_another_process(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    script = (
        "from copium.install.runtime import acquire_runtime_start_lock\n"
        "with acquire_runtime_start_lock('default') as acquired:\n"
        "    print(acquired)\n"
    )
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(Path.cwd())}

    with acquire_runtime_start_lock("default") as acquired:
        assert acquired is True
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            env=env,
            text=True,
        )

    assert result.stdout.strip() == "False"


def test_run_foreground_and_detached_helpers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "copium.install.runtime.build_runtime_command", lambda manifest: ["copium", "proxy"]
    )
    monkeypatch.setattr("copium.install.runtime._runtime_env", lambda manifest: {"ENV": "1"})
    signal_calls: list[int] = []
    monkeypatch.setattr(
        "copium.install.runtime.signal.signal", lambda sig, fn: signal_calls.append(sig)
    )

    class FakeProc:
        def __init__(self, returncode: int = 0, pid: int = 321) -> None:
            self.returncode = returncode
            self.pid = pid
            self.terminated = False
            self.killed = False

        def wait(self, timeout: int | None = None) -> int:
            return self.returncode

        def poll(self):
            return None if not self.terminated else self.returncode

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

    fake_proc = FakeProc(returncode=7)
    popen_calls: list[tuple[list[str], dict]] = []

    def fake_popen(command: list[str], **kwargs):
        popen_calls.append((command, kwargs))
        return fake_proc

    monkeypatch.setattr("copium.install.runtime.subprocess.Popen", fake_popen)
    manifest = DeploymentManifest(
        profile="default",
        preset="persistent-service",
        runtime_kind="python",
        supervisor_kind="service",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
    )
    assert run_foreground(manifest) == 7
    assert popen_calls[0][0] == ["copium", "proxy"]
    assert signal.SIGINT in signal_calls
    assert signal.SIGTERM in signal_calls
    assert _read_pid("default") is None

    monkeypatch.setattr("copium.install.runtime.resolve_copium_command", lambda: ["copium"])
    monkeypatch.setattr("copium.install.runtime.sys.platform", "win32")
    monkeypatch.setattr("copium.install.runtime.subprocess.DETACHED_PROCESS", 1, raising=False)
    monkeypatch.setattr(
        "copium.install.runtime.subprocess.CREATE_NEW_PROCESS_GROUP", 2, raising=False
    )
    fake_proc_nt = FakeProc()
    monkeypatch.setattr(
        "copium.install.runtime.subprocess.Popen", lambda command, **kwargs: fake_proc_nt
    )
    assert start_detached_agent("demo") is fake_proc_nt

    monkeypatch.setattr("copium.install.runtime.sys.platform", "linux")
    fake_proc_posix = FakeProc()
    monkeypatch.setattr(
        "copium.install.runtime.subprocess.Popen", lambda command, **kwargs: fake_proc_posix
    )
    assert start_detached_agent("demo") is fake_proc_posix


def test_start_stop_wait_and_runtime_status_branches(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "copium.install.runtime.subprocess.run",
        lambda command, **kwargs: calls.append(command) or type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(
        "copium.install.runtime.build_runtime_command",
        lambda manifest: [
            "docker",
            "run",
            "--rm",
            "--name",
            "demo",
            "-p",
            "127.0.0.1:8787:8787",
            "image",
        ],
    )
    manifest = DeploymentManifest(
        profile="default",
        preset=InstallPreset.PERSISTENT_DOCKER.value,
        runtime_kind="docker",
        supervisor_kind="none",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        container_name="copium-default",
    )
    start_persistent_docker(manifest)
    assert calls == [
        ["docker", "rm", "-f", "copium-default"],
        [
            "docker",
            "run",
            "-d",
            "--restart",
            "unless-stopped",
            "--name",
            "copium-default",
            "-p",
            "127.0.0.1:8787:8787",
            "image",
        ],
    ]

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    python_manifest = DeploymentManifest(
        profile="default",
        preset="persistent-service",
        runtime_kind="python",
        supervisor_kind="service",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        health_url="http://127.0.0.1:8787/health",
    )
    _write_pid("default", 123)
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "copium.install.runtime.os.kill", lambda pid, sig: killed.append((pid, sig))
    )
    stop_runtime(python_manifest)
    assert killed == [(123, signal.SIGTERM)]
    assert _read_pid("default") is None

    _write_pid("default", 124)
    monkeypatch.setattr(
        "copium.install.runtime.os.kill",
        lambda pid, sig: (_ for _ in ()).throw(OSError("gone")),
    )
    stop_runtime(python_manifest)
    assert _read_pid("default") is None

    probe_results = iter([False, False, True])
    sleeps: list[int] = []
    monkeypatch.setattr("copium.install.runtime.probe_ready", lambda url: next(probe_results))
    monkeypatch.setattr(
        "copium.install.runtime.time.sleep", lambda seconds: sleeps.append(seconds)
    )
    assert wait_ready(python_manifest, timeout_seconds=3) is True
    assert sleeps == [1, 1]

    monkeypatch.setattr("copium.install.runtime.probe_ready", lambda url: False)
    sleeps.clear()
    assert wait_ready(python_manifest, timeout_seconds=2) is False
    assert sleeps == [1, 1]

    class Result:
        def __init__(self, stdout: str = "") -> None:
            self.stdout = stdout

    monkeypatch.setattr(
        "copium.install.runtime.subprocess.run",
        lambda command, **kwargs: Result(stdout=""),
    )
    assert runtime_status(manifest) == "stopped"
    assert runtime_status(python_manifest) == "stopped"

    _write_pid("default", 125)
    monkeypatch.setattr(
        "copium.install.runtime.os.kill", lambda pid, sig: (_ for _ in ()).throw(OSError())
    )
    assert runtime_status(python_manifest) == "stopped"


def test_stop_runtime_for_docker_stops_and_removes_container(monkeypatch) -> None:
    calls: list[list[str]] = []
    manifest = DeploymentManifest(
        profile="default",
        preset="persistent-docker",
        runtime_kind="docker",
        supervisor_kind="none",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        container_name="copium-default",
    )

    monkeypatch.setattr(
        "copium.install.runtime.subprocess.run",
        lambda command, **kwargs: calls.append(command),
    )

    stop_runtime(manifest)

    assert calls == [
        ["docker", "stop", "copium-default"],
        ["docker", "rm", "-f", "copium-default"],
    ]


def test_runtime_status_reads_container_and_pid_state(monkeypatch, tmp_path: Path) -> None:
    docker_manifest = DeploymentManifest(
        profile="default",
        preset="persistent-docker",
        runtime_kind="docker",
        supervisor_kind="none",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        container_name="copium-default",
    )

    class Result:
        def __init__(self, stdout: str = "") -> None:
            self.stdout = stdout

    monkeypatch.setattr(
        "copium.install.runtime.subprocess.run",
        lambda command, **kwargs: Result(stdout="copium-default\n"),
    )
    assert runtime_status(docker_manifest) == "running"

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    pid_file = tmp_path / ".copium" / "deploy" / "default" / "runner.pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("123", encoding="utf-8")
    monkeypatch.setattr("copium.install.runtime.os.kill", lambda pid, sig: None)
    python_manifest = DeploymentManifest(
        profile="default",
        preset="persistent-service",
        runtime_kind="python",
        supervisor_kind="service",
        scope="user",
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
    )
    assert runtime_status(python_manifest) == "running"
