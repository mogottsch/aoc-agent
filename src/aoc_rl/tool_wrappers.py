from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import ExecuteResult, execute_python
from aoc_agent.tools.submit import SubmitResult, submit_answer
from pydantic_ai import RunContext

from aoc_agent.tools.context import ToolContext


async def call_execute_python(
    ctx: RunContext[ToolContext],
    code: str,
    *,
    max_output_length: int = 2000,
    timeout_seconds: float = 30.0,
) -> ExecuteResult:
    return await execute_python(
        ctx,
        code,
        max_output_length=max_output_length,
        timeout_seconds=timeout_seconds,
    )


def call_problem_description(ctx: RunContext[ToolContext]) -> str:
    return get_aoc_problem_description(ctx)


def call_submit_answer(ctx: RunContext[ToolContext], part: int, answer: int | str) -> SubmitResult:
    return submit_answer(ctx, part, answer)
