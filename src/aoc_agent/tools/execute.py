from typing import cast

from jupyter_client.asynchronous.client import AsyncKernelClient
from pydantic import BaseModel
from pydantic_ai import RunContext

from aoc_agent.adapters.execution.jupyter_executor import JupyterExecutor
from aoc_agent.tools.context import ToolContext


class ExecuteResult(BaseModel):
    output: str
    error: str


async def execute_python(ctx: RunContext[ToolContext], code: str) -> ExecuteResult:
    client = ctx.deps.kernel_client
    if client is None:
        raise RuntimeError("kernel_client not set")

    kernel_client = cast(AsyncKernelClient, client)
    executor = JupyterExecutor(kernel_client)
    stdout, stderr = await executor.execute(code, input_content=ctx.deps.input_content)
    return ExecuteResult(output=stdout, error=stderr)
