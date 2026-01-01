import pytest

from aoc_agent.adapters.execution.jupyter import jupyter_context
from aoc_agent.adapters.execution.jupyter_executor import ExecutionTimeoutError, JupyterExecutor
from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.context import ToolContext


@pytest.mark.asyncio
async def test_executor_times_out_and_interrupts_kernel() -> None:
    base_ctx = ToolContext(
        year=2024,
        day=1,
        input_content="",
        solve_status=SolveStatus(),
    )
    async with jupyter_context(base_ctx) as ctx:
        executor = JupyterExecutor(ctx.kernel_client, ctx.kernel_manager)

        with pytest.raises(ExecutionTimeoutError) as exc_info:
            await executor.execute(
                "import time; time.sleep(999)",
                input_content="",
                timeout_seconds=0.1,
            )

        assert exc_info.value.timeout_seconds == 0.1
        assert "0.1s" in str(exc_info.value)

        stdout, _ = await executor.execute(
            "print('still alive')",
            input_content="",
            timeout_seconds=5.0,
        )
        assert "still alive" in stdout


@pytest.mark.asyncio
async def test_executor_completes_within_timeout() -> None:
    base_ctx = ToolContext(
        year=2024,
        day=1,
        input_content="",
        solve_status=SolveStatus(),
    )
    async with jupyter_context(base_ctx) as ctx:
        executor = JupyterExecutor(ctx.kernel_client, ctx.kernel_manager)

        stdout, stderr = await executor.execute(
            "import time; time.sleep(0.05); print('done')",
            input_content="",
            timeout_seconds=5.0,
        )

        assert "done" in stdout
        assert stderr == ""


@pytest.mark.asyncio
async def test_interrupt_preserves_variables() -> None:
    base_ctx = ToolContext(
        year=2024,
        day=1,
        input_content="",
        solve_status=SolveStatus(),
    )
    async with jupyter_context(base_ctx) as ctx:
        executor = JupyterExecutor(ctx.kernel_client, ctx.kernel_manager)

        await executor.execute("x = 42", input_content="", timeout_seconds=5.0)

        with pytest.raises(ExecutionTimeoutError):
            await executor.execute(
                "import time; time.sleep(999)",
                input_content="",
                timeout_seconds=0.1,
            )

        stdout, _ = await executor.execute("print(x)", input_content="", timeout_seconds=5.0)
        assert "42" in stdout
