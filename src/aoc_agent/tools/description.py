import logfire
from pydantic_ai import RunContext

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.tools.context import ToolContext


def get_aoc_problem_description(ctx: RunContext[ToolContext]) -> str:
    service = get_aoc_data_service()
    data = service.get(ctx.deps.year, ctx.deps.day)

    logfire.info(
        "get_aoc_problem_description",
        year=ctx.deps.year,
        day=ctx.deps.day,
        part1_solved=ctx.deps.solve_status.part1_solved,
    )

    if ctx.deps.solve_status.part1_solved:
        return data.problem_html.part1_solved_html or data.problem_html.unsolved_html

    return data.problem_html.unsolved_html
