import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aoc_agent.adapters.execution.jupyter import jupyter_context
from aoc_agent.core.models import SolveStatus
from aoc_agent.core.settings import get_settings
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.execute import execute_python
from tests._helpers import as_run_context


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["start_channels", "wait_for_ready"])
async def test_kernel_startup_failure_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    manager = MagicMock()
    manager.start_kernel = AsyncMock()
    manager.shutdown_kernel = AsyncMock()
    manager.cleanup_resources = AsyncMock()
    client = manager.client.return_value
    client.wait_for_ready = AsyncMock()
    getattr(client, failure).side_effect = RuntimeError("startup failed")
    monkeypatch.setattr(
        "aoc_agent.adapters.execution.jupyter.SandboxedKernelManager",
        lambda: manager,
    )
    base_ctx = ToolContext(year=2024, day=1, input_content="", solve_status=SolveStatus())

    with pytest.raises(RuntimeError, match="startup failed"):
        async with jupyter_context(base_ctx):
            pytest.fail("startup failure must not yield an executor")

    client.stop_channels.assert_called_once()
    manager.shutdown_kernel.assert_awaited_once_with(now=True)
    manager.cleanup_resources.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS integration requires Linux")
async def test_real_rlimit_kernel_numpy_memory_errors_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # NumPy is not a project dependency. Reuse an explicitly supplied compatible
    # installation for this offline integration test; never install at test time.
    numpy_path = os.environ.get("AOC_TEST_NUMPY_PATH")
    if numpy_path:
        monkeypatch.setenv("PYTHONPATH", numpy_path)
    elif importlib.util.find_spec("numpy") is None:
        pytest.skip("NumPy unavailable; supply compatible AOC_TEST_NUMPY_PATH")
    monkeypatch.setenv("AOC_SESSION_TOKEN", "test-session")
    monkeypatch.setenv("EXECUTION_SANDBOX", "rlimit")
    monkeypatch.setenv("EXECUTION_MEMORY_MB", "4096")
    monkeypatch.delenv("EXECUTION_CPU_QUOTA_PERCENT", raising=False)
    monkeypatch.delenv("EXECUTION_TASKS_MAX", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    base_ctx = ToolContext(year=2024, day=1, input_content="2\n3", solve_status=SolveStatus())
    try:
        async with jupyter_context(base_ctx) as deps:
            ctx = as_run_context(deps)
            first = await execute_python(
                ctx,
                "import resource, sys; "
                "print(resource.getrlimit(resource.RLIMIT_AS)); print(sys.executable)",
                timeout_seconds=10,
            )
            assert first.error == ""
            assert first.output.splitlines() == ["(4294967296, 4294967296)", sys.executable]

            normal = await execute_python(
                ctx,
                "import numpy as np; print(np.arange(5).sum()); "
                "print(sum(map(int, input_content.splitlines())))",
                timeout_seconds=10,
            )
            assert normal.error == ""
            assert normal.output == "10\n5\n"

            for code in (
                "x = bytearray(5 * 1024**3)",
                "x = np.ones(5 * 1024**3, dtype=np.uint8)",
            ):
                oversized = await execute_python(ctx, code, timeout_seconds=10)
                assert "MemoryError" in oversized.error
                recovered = await execute_python(ctx, "print(np.arange(5).sum())")
                assert recovered.error == ""
                assert recovered.output == "10\n"

            raised = await execute_python(
                ctx,
                "resource.setrlimit(resource.RLIMIT_AS, "
                "(resource.RLIM_INFINITY, resource.RLIM_INFINITY))",
            )
            assert "ValueError" in raised.error

            child_source = (
                "import resource\nprint(resource.getrlimit(resource.RLIMIT_AS))\n"
                "try:\n    bytearray(5 * 1024**3)\n"
                "except MemoryError:\n    print('child MemoryError')\n"
            )
            child = await execute_python(
                ctx,
                f"import subprocess; child_code = {child_source!r}; "
                "print(subprocess.check_output([sys.executable, '-c', child_code], "
                "text=True).strip())",
                timeout_seconds=10,
            )
            assert child.error == ""
            assert child.output == "(4294967296, 4294967296)\nchild MemoryError\n"
    finally:
        get_settings.cache_clear()
