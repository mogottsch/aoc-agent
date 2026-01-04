import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from jupyter_client import AsyncKernelManager

from aoc_agent.adapters.execution.jupyter_executor import JupyterExecutor
from aoc_agent.tools.context import ToolContext


@asynccontextmanager
async def jupyter_context(context: ToolContext) -> AsyncIterator[ToolContext]:
    km = AsyncKernelManager()
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
