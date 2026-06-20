from __future__ import annotations

from pathlib import Path

import click
import pytest

from copium.install.models import DeploymentManifest, SupervisorKind
from copium.install.supervisors import (
    _command_for_script,
    _linux_service_unit,
    _linux_task_spec,
    _macos_launchd_plist,
    _render_unix_runner,
    _render_windows_runner,
    install_supervisor,
    remove_supervisor,
    render_runner_scripts,
    start_supervisor,
    stop_supervisor,
)


def _manifest(
    *, profile: str = "default", scope: str = "user", supervisor: str = "service"
) -> DeploymentManifest:
    return DeploymentManifest(
        profile=profile,
        preset="persistent-service",
        runtime_kind="python",
        supervisor_kind=supervisor,
        scope=scope,
        provider_mode="manual",
        targets=[],
        port=8787,
        host="127.0.0.1",
        backend="anthropic",
        service_name=f"copium-{profile}",
    )


def test_linux_service_unit_uses_user_systemd_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    manifest = _manifest()

    unit_path, content = _linux_service_unit(manifest, tmp_path / "run-copium.sh")

    assert unit_path == tmp_path / ".config" / "systemd" / "user" / "copium-default.service"
    assert "ExecStart=" + str(tmp_path / "run-copium.sh") in content
    assert "Restart=on-failure" in content


def test_command_for_script_and_unix_runner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "copium.install.supervisors.resolve_copium_command",
        lambda: ["python", "-m", "copium"],
    )

    assert _command_for_script("install", "agent", "run") == [
        "python",
        "-m",
        "copium",
        "install",
        "agent",
        "run",
    ]

    record = _render_unix_runner(
        tmp_path / "scripts" / "run-copium.sh", ["copium", "run", "--flag"]
    )
    assert record.kind == "script"
    content = Path(record.path).read_text(encoding="utf-8")
    assert content.startswith("#!/usr/bin/env bash")
    assert "exec copium run --flag" in content


def test_linux_task_spec_for_user_scope_includes_crontab_markers(tmp_path: Path) -> None:
    manifest = _manifest(profile="smoke", supervisor=SupervisorKind.TASK.value)

    cron_path, content = _linux_task_spec(manifest, tmp_path / "ensure-copium.sh")

    assert cron_path is None
    assert "# >>> copium smoke >>>" in content
    assert "# <<< copium smoke <<<" in content
    assert "@reboot" in content
    assert "*/5 * * * *" in content


def test_macos_launchd_plist_switches_between_keepalive_and_interval(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    service_manifest = _manifest(supervisor=SupervisorKind.SERVICE.value)
    service_path, service_content = _macos_launchd_plist(
        service_manifest, tmp_path / "run-copium.sh"
    )
    assert service_path == tmp_path / "Library" / "LaunchAgents" / "com.copium.default.plist"
    assert "<key>KeepAlive</key>" in service_content
    assert "<key>StartInterval</key>" not in service_content

    task_manifest = _manifest(profile="tasky", supervisor=SupervisorKind.TASK.value)
    task_path, task_content = _macos_launchd_plist(
        task_manifest, tmp_path / "ensure-copium.sh", interval=300
    )
    assert task_path == tmp_path / "Library" / "LaunchAgents" / "com.copium.tasky.plist"
    assert "<key>StartInterval</key>" in task_content
    assert "<integer>300</integer>" in task_content


def test_render_windows_runner_writes_ps1_and_cmd_wrappers(tmp_path: Path) -> None:
    ps1_path = tmp_path / "run-copium.ps1"
    cmd_path = tmp_path / "run-copium.cmd"

    records = _render_windows_runner(
        ps1_path,
        cmd_path,
        ["C:\\Program Files\\Python\\python.exe", "copium", "install", "agent", "run"],
    )

    assert [record.path for record in records] == [str(ps1_path), str(cmd_path)]
    ps1_content = ps1_path.read_text(encoding="utf-8")
    cmd_content = cmd_path.read_text(encoding="utf-8")
    assert '& "C:\\Program Files\\Python\\python.exe" copium install agent run' in ps1_content
    assert (
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-copium.ps1" %*'
        in cmd_content
    )


def test_render_runner_scripts_writes_unix_scripts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "linux")
    monkeypatch.setattr(
        "copium.install.supervisors.resolve_copium_command", lambda: ["copium"]
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    manifest = _manifest()

    records = render_runner_scripts(manifest)

    assert {record.path.split("\\")[-1].split("/")[-1] for record in records} == {
        "run-copium.sh",
        "ensure-copium.sh",
    }


def test_render_runner_scripts_writes_windows_scripts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "win32")
    monkeypatch.setattr(
        "copium.install.supervisors.resolve_copium_command", lambda: ["copium.exe"]
    )
    monkeypatch.setattr(
        "copium.install.supervisors.windows_run_script_path",
        lambda profile: tmp_path / "run-copium.ps1",
    )
    monkeypatch.setattr(
        "copium.install.supervisors.windows_run_cmd_path",
        lambda profile: tmp_path / "run-copium.cmd",
    )
    monkeypatch.setattr(
        "copium.install.supervisors.windows_ensure_script_path",
        lambda profile: tmp_path / "ensure-copium.ps1",
    )
    monkeypatch.setattr(
        "copium.install.supervisors.windows_ensure_cmd_path",
        lambda profile: tmp_path / "ensure-copium.cmd",
    )

    records = render_runner_scripts(_manifest(profile="win"))

    assert [Path(record.path).name for record in records] == [
        "run-copium.ps1",
        "run-copium.cmd",
        "ensure-copium.ps1",
        "ensure-copium.cmd",
    ]


def test_install_supervisor_none_returns_runner_records(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "linux")
    monkeypatch.setattr(
        "copium.install.supervisors.resolve_copium_command", lambda: ["copium"]
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    manifest = _manifest(supervisor=SupervisorKind.NONE.value)

    records = install_supervisor(manifest)

    assert len(records) == 2
    assert all(record.kind == "script" for record in records)


def test_start_and_stop_supervisor_use_linux_systemctl(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "linux")
    monkeypatch.setattr(
        "copium.install.supervisors.subprocess.run",
        lambda command, **kwargs: calls.append(command),
    )
    manifest = _manifest()

    start_supervisor(manifest)
    stop_supervisor(manifest)

    assert calls == [
        ["systemctl", "--user", "restart", "copium-default"],
        ["systemctl", "--user", "stop", "copium-default"],
    ]


def test_install_supervisor_linux_service_and_tasks(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "linux")
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "linux")
    run_script = tmp_path / "run-copium.sh"
    ensure_script = tmp_path / "ensure-copium.sh"
    monkeypatch.setattr(
        "copium.install.supervisors.render_runner_scripts",
        lambda manifest: [
            type("Record", (), {"kind": "script", "path": run_script.as_posix()})(),
            type("Record", (), {"kind": "script", "path": ensure_script.as_posix()})(),
        ],
    )
    unit_path = tmp_path / "copium-default.service"
    monkeypatch.setattr(
        "copium.install.supervisors._linux_service_unit",
        lambda manifest, script: (unit_path, "UNIT"),
    )
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "# old cron\n"})()

    monkeypatch.setattr("copium.install.supervisors.subprocess.run", fake_run)

    service_records = install_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    assert unit_path.read_text(encoding="utf-8") == "UNIT"
    assert ["systemctl", "--user", "daemon-reload"] in [call[0] for call in calls]
    assert ["systemctl", "--user", "enable", "copium-default"] in [call[0] for call in calls]
    assert service_records[-1].kind == "service-unit"

    cron_path = tmp_path / "copium-system"
    monkeypatch.setattr(
        "copium.install.supervisors._linux_task_spec",
        lambda manifest, script: (cron_path, "@reboot root ensure\n"),
    )
    system_task_records = install_supervisor(
        _manifest(profile="system-task", scope="system", supervisor=SupervisorKind.TASK.value)
    )
    assert cron_path.read_text(encoding="utf-8") == "@reboot root ensure\n"
    assert system_task_records[-1].kind == "cron"

    monkeypatch.setattr(
        "copium.install.supervisors._linux_task_spec",
        lambda manifest, script: (
            None,
            "# >>> copium default >>>\n@reboot ensure\n# <<< copium default <<<\n",
        ),
    )
    user_task_records = install_supervisor(_manifest(supervisor=SupervisorKind.TASK.value))
    assert user_task_records[-1].kind == "crontab"
    assert calls[-1][0] == ["crontab", "-"]
    assert "@reboot ensure" in calls[-1][1]["input"]


def test_install_supervisor_darwin_windows_and_unsupported(monkeypatch, tmp_path: Path) -> None:
    run_script = tmp_path / "run-copium.sh"
    ensure_script = tmp_path / "ensure-copium.sh"
    monkeypatch.setattr(
        "copium.install.supervisors.render_runner_scripts",
        lambda manifest: [
            type("Record", (), {"kind": "script", "path": run_script.as_posix()})(),
            type("Record", (), {"kind": "script", "path": ensure_script.as_posix()})(),
        ],
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "copium.install.supervisors.subprocess.run",
        lambda command, **kwargs: calls.append(command),
    )
    monkeypatch.setattr("copium.install.supervisors.os.getuid", lambda: 123, raising=False)

    plist_path = tmp_path / "com.copium.default.plist"
    monkeypatch.setattr(
        "copium.install.supervisors._macos_launchd_plist",
        lambda manifest, script, interval=None: (plist_path, f"plist-{interval}"),
    )
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "darwin")
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "darwin")
    service_records = install_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    task_records = install_supervisor(_manifest(supervisor=SupervisorKind.TASK.value))
    assert plist_path.read_text(encoding="utf-8") == "plist-300"
    assert service_records[-1].kind == "plist"
    assert task_records[-1].kind == "plist"
    assert ["launchctl", "bootstrap", "gui/123", str(plist_path)] in calls

    monkeypatch.setattr("copium.install.supervisors.sys.platform", "win32")
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "win32")
    monkeypatch.setattr(
        "copium.install.supervisors.windows_run_cmd_path",
        lambda profile: Path(f"C:\\tmp\\{profile}\\run-copium.cmd"),
    )
    monkeypatch.setattr(
        "copium.install.supervisors.windows_ensure_cmd_path",
        lambda profile: Path(f"C:\\tmp\\{profile}\\ensure-copium.cmd"),
    )
    win_service = install_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    win_task = install_supervisor(_manifest(supervisor=SupervisorKind.TASK.value))
    assert win_service[-1].kind == "windows-service"
    assert win_task[-2].path.endswith("-startup")
    assert [
        "sc.exe",
        "create",
        "copium-default",
        'binPath= cmd.exe /c "C:\\tmp\\default\\run-copium.cmd"',
        "start= auto",
    ] in calls
    assert [
        "schtasks",
        "/Create",
        "/TN",
        "copium-default-health",
        "/TR",
        "C:\\tmp\\default\\ensure-copium.cmd",
        "/SC",
        "MINUTE",
        "/MO",
        "5",
        "/F",
    ] in calls

    monkeypatch.setattr("copium.install.supervisors.sys.platform", "plan9")
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "plan9")
    with pytest.raises(click.ClickException, match="not supported"):
        install_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))


def test_start_and_stop_supervisor_darwin_windows_and_none(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "copium.install.supervisors.subprocess.run",
        lambda command, **kwargs: calls.append(command),
    )
    monkeypatch.setattr("copium.install.supervisors.os.getuid", lambda: 77, raising=False)

    start_supervisor(_manifest(supervisor=SupervisorKind.NONE.value))
    stop_supervisor(_manifest(supervisor=SupervisorKind.NONE.value))
    assert calls == []

    monkeypatch.setattr("copium.install.supervisors.sys.platform", "darwin")
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "darwin")
    start_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    stop_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    assert calls == [
        ["launchctl", "kickstart", "-k", "gui/77/com.copium.default"],
        ["launchctl", "bootout", "gui/77/com.copium.default"],
    ]

    calls.clear()
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "win32")
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "win32")
    start_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    stop_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    assert calls == [
        ["sc.exe", "start", "copium-default"],
        ["sc.exe", "stop", "copium-default"],
    ]


def test_remove_supervisor_removes_user_crontab_block(monkeypatch) -> None:
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "linux")

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(command: list[str], **kwargs):
        calls.append((command, kwargs.get("input")))
        if command == ["crontab", "-l"]:
            return Result(
                stdout="# >>> copium default >>>\n@reboot /tmp/ensure\n# <<< copium default <<<\n"
            )
        return Result()

    monkeypatch.setattr("copium.install.supervisors.subprocess.run", fake_run)
    manifest = _manifest(supervisor=SupervisorKind.TASK.value)

    remove_supervisor(manifest)

    assert calls[0][0] == ["crontab", "-l"]
    assert calls[1][0] == ["crontab", "-"]


def test_remove_supervisor_linux_service_cron_path_and_missing_crontab(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "linux")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 1, "stdout": ""})()

    monkeypatch.setattr("copium.install.supervisors.subprocess.run", fake_run)
    unit_path = tmp_path / "copium-default.service"
    unit_path.write_text("unit", encoding="utf-8")
    monkeypatch.setattr(
        "copium.install.supervisors._linux_service_unit",
        lambda manifest, script: (unit_path, "unit"),
    )
    remove_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    assert not unit_path.exists()
    assert ["systemctl", "--user", "disable", "--now", "copium-default"] in calls
    assert ["systemctl", "--user", "daemon-reload"] in calls

    cron_path = tmp_path / "copium-task"
    cron_path.write_text("cron", encoding="utf-8")
    monkeypatch.setattr(
        "copium.install.supervisors._linux_task_spec",
        lambda manifest, script: (cron_path, "cron"),
    )
    remove_supervisor(_manifest(supervisor=SupervisorKind.TASK.value))
    assert not cron_path.exists()

    monkeypatch.setattr(
        "copium.install.supervisors._linux_task_spec",
        lambda manifest, script: (None, "cron"),
    )
    remove_supervisor(_manifest(supervisor=SupervisorKind.TASK.value))
    assert calls[-1] == ["crontab", "-l"]


def test_remove_supervisor_darwin_and_windows(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "copium.install.supervisors.subprocess.run",
        lambda command, **kwargs: calls.append(command),
    )
    monkeypatch.setattr("copium.install.supervisors.os.getuid", lambda: 55, raising=False)

    plist_path = tmp_path / "com.copium.default.plist"
    plist_path.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(
        "copium.install.supervisors.unix_run_script_path",
        lambda profile: tmp_path / "run-copium.sh",
    )
    monkeypatch.setattr(
        "copium.install.supervisors.unix_ensure_script_path",
        lambda profile: tmp_path / "ensure-copium.sh",
    )
    monkeypatch.setattr(
        "copium.install.supervisors._macos_launchd_plist",
        lambda manifest, script, interval=None: (plist_path, "plist"),
    )
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "darwin")
    remove_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    assert not plist_path.exists()
    assert calls[0] == ["launchctl", "bootout", "gui/55/com.copium.default"]

    calls.clear()
    monkeypatch.setattr("copium.install.supervisors.sys.platform", "win32")
    remove_supervisor(_manifest(supervisor=SupervisorKind.SERVICE.value))
    remove_supervisor(_manifest(supervisor=SupervisorKind.TASK.value))
    assert calls == [
        ["sc.exe", "stop", "copium-default"],
        ["sc.exe", "delete", "copium-default"],
        ["schtasks", "/Delete", "/TN", "copium-default-startup", "/F"],
        ["schtasks", "/Delete", "/TN", "copium-default-health", "/F"],
    ]
