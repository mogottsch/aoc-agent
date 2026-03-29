import pytest
from pydantic import ValidationError

from aoc_agent.adapters.execution.jupyter import SandboxedKernelManager
from aoc_agent.adapters.execution.sandbox import (
    ExecutionSandboxSettings,
)
from aoc_agent.core.settings import ExecutionSandbox, Settings, get_settings


def test_get_settings_execution_sandbox_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXECUTION_SANDBOX", raising=False)
    monkeypatch.delenv("EXECUTION_MEMORY_MB", raising=False)
    monkeypatch.delenv("EXECUTION_CPU_QUOTA_PERCENT", raising=False)
    monkeypatch.delenv("EXECUTION_TASKS_MAX", raising=False)
    get_settings.cache_clear()

    app_settings = get_settings()
    settings = ExecutionSandboxSettings(
        backend=app_settings.execution_sandbox,
        memory_mb=app_settings.execution_memory_mb,
        cpu_quota_percent=app_settings.execution_cpu_quota_percent,
        tasks_max=app_settings.execution_tasks_max,
    )

    assert settings == ExecutionSandboxSettings()


def test_get_settings_execution_sandbox_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_SANDBOX", "cgroup")
    monkeypatch.setenv("EXECUTION_MEMORY_MB", "768")
    monkeypatch.setenv("EXECUTION_CPU_QUOTA_PERCENT", "150")
    monkeypatch.setenv("EXECUTION_TASKS_MAX", "128")
    get_settings.cache_clear()

    app_settings = get_settings()
    settings = ExecutionSandboxSettings(
        backend=app_settings.execution_sandbox,
        memory_mb=app_settings.execution_memory_mb,
        cpu_quota_percent=app_settings.execution_cpu_quota_percent,
        tasks_max=app_settings.execution_tasks_max,
    )

    assert settings.backend == ExecutionSandbox.CGROUP
    assert settings.memory_mb == 768
    assert settings.cpu_quota_percent == 150
    assert settings.tasks_max == 128


def test_local_sandbox_rejects_custom_limits() -> None:
    with pytest.raises(
        ValidationError, match="EXECUTION_MEMORY_MB requires EXECUTION_SANDBOX=cgroup"
    ):
        Settings.model_validate(
            {
                "AOC_SESSION_TOKEN": "test-session",
                "EXECUTION_SANDBOX": "local",
                "EXECUTION_MEMORY_MB": 768,
            },
            by_alias=True,
        )


def test_wrap_kernel_command_local() -> None:
    settings = ExecutionSandboxSettings()

    assert settings.wrap_kernel_command(["python", "-m", "ipykernel_launcher"]) == [
        "python",
        "-m",
        "ipykernel_launcher",
    ]


def test_wrap_kernel_command_cgroup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aoc_agent.adapters.execution.sandbox.shutil.which", lambda name: "/usr/bin/systemd-run"
    )
    settings = ExecutionSandboxSettings(
        backend=ExecutionSandbox.CGROUP,
        memory_mb=256,
        cpu_quota_percent=75,
        tasks_max=32,
    )

    command = settings.wrap_kernel_command(["python", "-m", "ipykernel_launcher"])

    assert command == [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--property=MemoryMax=256M",
        "--property=CPUQuota=75%",
        "--property=TasksMax=32",
        "python",
        "-m",
        "ipykernel_launcher",
    ]


def test_wrap_kernel_command_cgroup_requires_systemd_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aoc_agent.adapters.execution.sandbox.shutil.which", lambda name: None)
    settings = ExecutionSandboxSettings(backend=ExecutionSandbox.CGROUP)

    with pytest.raises(RuntimeError, match="systemd-run"):
        settings.wrap_kernel_command(["python", "-m", "ipykernel_launcher"])


def test_sandboxed_kernel_manager_wraps_formatted_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_SANDBOX", "cgroup")
    monkeypatch.setenv("EXECUTION_MEMORY_MB", "384")
    monkeypatch.setenv("EXECUTION_CPU_QUOTA_PERCENT", "80")
    monkeypatch.setenv("EXECUTION_TASKS_MAX", "40")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "aoc_agent.adapters.execution.sandbox.shutil.which", lambda name: "/usr/bin/systemd-run"
    )

    km = SandboxedKernelManager()
    command = km.format_kernel_cmd()

    assert command[:7] == [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--property=MemoryMax=384M",
        "--property=CPUQuota=80%",
        "--property=TasksMax=40",
    ]
    assert "{connection_file}" not in command


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
