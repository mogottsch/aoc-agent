import pytest
from pydantic import ValidationError

from aoc_agent.adapters.execution.sandbox import ExecutionSandboxSettings
from aoc_agent.core.settings import Settings


@pytest.mark.parametrize("memory", [512, "512", True, 4096.0, b"4096"])
def test_bytes_backend_cannot_bypass_strict_memory(memory: object) -> None:
    with pytest.raises(ValidationError):
        ExecutionSandboxSettings.model_validate({"backend": b"rlimit", "memory_mb": memory})
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "AOC_SESSION_TOKEN": "OFFLINE_NOT_A_COOKIE",
                "EXECUTION_SANDBOX": b"rlimit",
                "EXECUTION_MEMORY_MB": memory,
            }
        )


def test_bytes_backend_with_exact_memory_is_consistent() -> None:
    settings = ExecutionSandboxSettings.model_validate({"backend": b"rlimit", "memory_mb": 4096})
    assert "4294967296" in settings.wrap_kernel_command(["python", "kernel.py"])[2]
