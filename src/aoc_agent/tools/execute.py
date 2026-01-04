from pydantic import BaseModel
from pydantic_ai import RunContext

from aoc_agent.adapters.execution.executor import ExecutionTimeoutError, TimeoutLimitExceededError
from aoc_agent.core.constants import (
    DEFAULT_MAX_OUTPUT_LENGTH,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
)
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
    max_output_length: int = DEFAULT_MAX_OUTPUT_LENGTH,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ExecuteResult:
    if ctx.deps.executor is None:
        raise RuntimeError("kernel not configured")

    if timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise TimeoutLimitExceededError(timeout_seconds, MAX_TIMEOUT_SECONDS)

    try:
        stdout, stderr = await ctx.deps.executor.execute(
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
