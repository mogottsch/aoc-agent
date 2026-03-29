import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from jupyter_client import AsyncKernelManager

from aoc_agent.adapters.execution.executor import JupyterExecutor
from aoc_agent.adapters.execution.sandbox import ExecutionSandboxSettings
from aoc_agent.core.settings import get_settings
from aoc_agent.tools.context import ToolContext


class SandboxedKernelManager(AsyncKernelManager):
    def format_kernel_cmd(self, extra_arguments: list[str] | None = None) -> list[str]:
        kernel_cmd = super().format_kernel_cmd(extra_arguments=extra_arguments)
        app_settings = get_settings()
        sandbox_settings = ExecutionSandboxSettings(
            backend=app_settings.execution_sandbox,
            memory_mb=app_settings.execution_memory_mb,
            cpu_quota_percent=app_settings.execution_cpu_quota_percent,
            tasks_max=app_settings.execution_tasks_max,
        )
        return sandbox_settings.wrap_kernel_command(kernel_cmd)


@asynccontextmanager
async def jupyter_context(context: ToolContext) -> AsyncIterator[ToolContext]:
    km = SandboxedKernelManager()
    await km.start_kernel()
    client = km.client()
    client.start_channels()
    async with asyncio.timeout(30):
        await client.wait_for_ready()

    executor = JupyterExecutor(client, km)
    try:
        yield context.model_copy(update={"executor": executor})
    finally:
        await executor.close()
