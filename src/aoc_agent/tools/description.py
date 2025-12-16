from pydantic_ai import RunContext

from aoc_agent.tools.context import ToolContext


def get_aoc_problem_description(ctx: RunContext[ToolContext]) -> str:
    """Get the current Advent of Code problem description.

    Returns the problem text, which updates to show Part 2 after Part 1 is solved.
    """
    if ctx.deps.solve_status.part1_solved:
        return ctx.deps.problem_html.part1_solved_html or ctx.deps.problem_html.unsolved_html

    return ctx.deps.problem_html.unsolved_html
