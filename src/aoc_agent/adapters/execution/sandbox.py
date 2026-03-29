import shutil

from pydantic import BaseModel

from aoc_agent.core.settings import ExecutionSandbox


class ExecutionSandboxSettings(BaseModel):
    backend: ExecutionSandbox = ExecutionSandbox.LOCAL
    memory_mb: int = 512
    cpu_quota_percent: int = 100
    tasks_max: int = 64

    def wrap_kernel_command(self, kernel_cmd: list[str]) -> list[str]:
        if self.backend == ExecutionSandbox.LOCAL:
            return kernel_cmd
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
