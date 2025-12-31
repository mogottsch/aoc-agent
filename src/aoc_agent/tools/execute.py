from typing import cast

from jupyter_client.asynchronous.client import AsyncKernelClient
from pydantic import BaseModel
from pydantic_ai import RunContext

from aoc_agent.adapters.execution.jupyter_executor import JupyterExecutor
from aoc_agent.tools.context import ToolContext


class ExecuteResult(BaseModel):
    output: str
    error: str


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return f"{text[:half]}\n\n... [TRUNCATED {len(text) - max_len} CHARS] ...\n\n{text[-half:]}"


async def execute_python(
    ctx: RunContext[ToolContext], code: str, max_output_length: int = 2000
) -> ExecuteResult:
    client = ctx.deps.kernel_client
    if client is None:
        raise RuntimeError("kernel_client not set")

    kernel_client = cast(AsyncKernelClient, client)
    executor = JupyterExecutor(kernel_client)
    stdout, stderr = await executor.execute(code, input_content=ctx.deps.input_content)
    return ExecuteResult(
        output=_truncate(stdout, max_output_length),
        error=_truncate(stderr, max_output_length),
    )
