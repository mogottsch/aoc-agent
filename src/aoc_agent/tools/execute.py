from typing import cast

from jupyter_client import AsyncKernelManager
from jupyter_client.asynchronous.client import AsyncKernelClient
from pydantic import BaseModel
from pydantic_ai import RunContext

from aoc_agent.adapters.execution.jupyter_executor import ExecutionTimeoutError, JupyterExecutor
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
    ctx: RunContext[ToolContext],
    code: str,
    max_output_length: int = 2000,
    timeout_seconds: float = 30.0,
) -> ExecuteResult:
    client = ctx.deps.kernel_client
    manager = ctx.deps.kernel_manager
    if client is None or manager is None:
        raise RuntimeError("kernel not configured")

    executor = JupyterExecutor(
        cast(AsyncKernelClient, client),
        cast(AsyncKernelManager, manager),
    )
    try:
        stdout, stderr = await executor.execute(
            code,
            input_content=ctx.deps.input_content,
            timeout_seconds=timeout_seconds,
        )
    except ExecutionTimeoutError as e:
        return ExecuteResult(output="", error=str(e))

    return ExecuteResult(
        output=_truncate(stdout, max_output_length),
        error=_truncate(stderr, max_output_length),
    )
