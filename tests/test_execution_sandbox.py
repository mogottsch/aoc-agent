import sys

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


def test_rlimit_env_wraps_kernel_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AOC_SESSION_TOKEN", "test-session")
    monkeypatch.setenv("EXECUTION_SANDBOX", "rlimit")
    monkeypatch.setenv("EXECUTION_MEMORY_MB", "4096")
    monkeypatch.delenv("EXECUTION_CPU_QUOTA_PERCENT", raising=False)
    monkeypatch.delenv("EXECUTION_TASKS_MAX", raising=False)
    settings = get_settings()
    assert settings.execution_memory_mb == 4096
    assert settings.execution_sandbox.value == "rlimit"

    # No shell interpolation: preserve argv, including spaces and metacharacters.
    kernel_cmd = ["/path with spaces/python", "-m", "ipykernel_launcher", "a;literal"]
    monkeypatch.setattr(
        "jupyter_client.AsyncKernelManager.format_kernel_cmd",
        lambda self, extra_arguments=None: kernel_cmd,
    )
    command = SandboxedKernelManager().format_kernel_cmd()
    assert command[:2] == [sys.executable, "-c"]
    assert "resource.setrlimit(resource.RLIMIT_AS, (4294967296, 4294967296))" in command[2]
    assert "os.execvp(sys.argv[1], sys.argv[1:])" in command[2]
    assert command[3:] == kernel_cmd


@pytest.mark.parametrize(
    "memory",
    [None, 0, -1, 512, 4095, 4097, 2**63, 4096.0, True, "4096.0", "4Gi", ""],
)
def test_rlimit_rejects_invalid_memory(memory: object) -> None:
    with pytest.raises(ValidationError, match="4096"):
        Settings.model_validate(
            {
                "AOC_SESSION_TOKEN": "test-session",
                "EXECUTION_SANDBOX": "rlimit",
                "EXECUTION_MEMORY_MB": memory,
            },
            by_alias=True,
        )
    with pytest.raises(ValidationError, match="4096"):
        ExecutionSandboxSettings.model_validate({"backend": "rlimit", "memory_mb": memory})


def test_rlimit_field_name_validation_cannot_bypass_literal_memory() -> None:
    with pytest.raises(ValidationError, match="4096"):
        Settings.model_validate(
            {
                "aoc_session_token": "test-session",
                "execution_sandbox": "rlimit",
                "execution_memory_mb": 4096.0,
            },
            by_name=True,
        )


def test_rlimit_requires_explicit_memory() -> None:
    with pytest.raises(ValidationError, match="4096"):
        Settings.model_validate(
            {"AOC_SESSION_TOKEN": "test-session", "EXECUTION_SANDBOX": "rlimit"},
            by_alias=True,
        )
    with pytest.raises(ValidationError, match="4096"):
        ExecutionSandboxSettings(backend="rlimit")


@pytest.mark.parametrize(
    ("setting", "adapter_setting", "value"),
    [
        ("EXECUTION_CPU_QUOTA_PERCENT", "cpu_quota_percent", 75),
        ("EXECUTION_TASKS_MAX", "tasks_max", 32),
    ],
)
def test_rlimit_rejects_unenforced_limits(
    setting: str,
    adapter_setting: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError, match="cgroup"):
        Settings.model_validate(
            {
                "AOC_SESSION_TOKEN": "test-session",
                "EXECUTION_SANDBOX": "rlimit",
                "EXECUTION_MEMORY_MB": 4096,
                setting: value,
            },
            by_alias=True,
        )
    with pytest.raises(ValidationError, match="cgroup"):
        ExecutionSandboxSettings(
            backend="rlimit",
            memory_mb=4096,
            **{adapter_setting: value},
        )


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
