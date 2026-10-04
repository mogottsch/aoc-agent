import shutil
import sys

from pydantic import BaseModel, model_validator

from aoc_agent.core.settings import (
    DEFAULT_EXECUTION_CPU_QUOTA_PERCENT,
    DEFAULT_EXECUTION_MEMORY_MB,
    DEFAULT_EXECUTION_TASKS_MAX,
    ExecutionSandbox,
    validate_rlimit_configuration,
)


class ExecutionSandboxSettings(BaseModel):
    backend: ExecutionSandbox = ExecutionSandbox.LOCAL
    memory_mb: int = 512
    cpu_quota_percent: int = 100
    tasks_max: int = 64

    @model_validator(mode="before")
    @classmethod
    def validate_rlimit_config(cls, values: object) -> object:
        if isinstance(values, dict):
            validate_rlimit_configuration(
                values.get("backend", ExecutionSandbox.LOCAL),
                values.get("memory_mb", DEFAULT_EXECUTION_MEMORY_MB),
                values.get("cpu_quota_percent", DEFAULT_EXECUTION_CPU_QUOTA_PERCENT),
                values.get("tasks_max", DEFAULT_EXECUTION_TASKS_MAX),
            )
        return values

    def wrap_kernel_command(self, kernel_cmd: list[str]) -> list[str]:
        if self.backend == ExecutionSandbox.LOCAL:
            return kernel_cmd
        if self.backend == ExecutionSandbox.RLIMIT:
            # Apply both limits before exec/imports; exec and descendants inherit them.
            # This is per-process virtual address space, not aggregate RSS isolation.
            limit_bytes = self.memory_mb * 1024 * 1024
            launcher = (
                "import os, resource, sys; "
                f"resource.setrlimit(resource.RLIMIT_AS, ({limit_bytes}, {limit_bytes})); "
                "os.execvp(sys.argv[1], sys.argv[1:])"
            )
            return [sys.executable, "-c", launcher, *kernel_cmd]
        return _wrap_with_systemd_run(kernel_cmd, self)


def _wrap_with_systemd_run(kernel_cmd: list[str], settings: ExecutionSandboxSettings) -> list[str]:
    if shutil.which("systemd-run") is None:
        msg = "EXECUTION_SANDBOX=cgroup requires systemd-run"
        raise RuntimeError(msg)
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        f"--property=MemoryMax={settings.memory_mb}M",
        f"--property=CPUQuota={settings.cpu_quota_percent}%",
        f"--property=TasksMax={settings.tasks_max}",
        *kernel_cmd,
    ]
