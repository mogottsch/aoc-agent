import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from jupyter_client import AsyncKernelManager

from aoc_agent.tools.context import ToolContext


@asynccontextmanager
async def jupyter_context(context: ToolContext) -> AsyncIterator[ToolContext]:
    km = AsyncKernelManager()
    await km.start_kernel()
    client = km.client()
    client.start_channels()
    async with asyncio.timeout(30):
        await client.wait_for_ready()
    try:
        yield context.model_copy(update={"kernel_manager": km, "kernel_client": client})
    finally:
        client.stop_channels()
        await km.shutdown_kernel(now=True)
        await km.cleanup_resources()
