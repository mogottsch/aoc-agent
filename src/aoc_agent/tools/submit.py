from bs4 import BeautifulSoup
from pydantic_ai import RunContext

from aoc_agent.adapters.aoc.client import get_aoc_client
from aoc_agent.tools.context import ToolContext


def _check_stored_answer(context: ToolContext, part: int, answer: str) -> bool | None:
    stored_answer = context.part1_answer if part == 1 else context.part2_answer
    if not stored_answer:
        return None

    return stored_answer == answer


def _parse_submit_response(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")

    if not main:
        raise ValueError("Could not parse response")

    main_text = main.get_text()

    return bool("That's the right answer" in main_text or "That's correct" in main_text)


def submit_answer(ctx: RunContext[ToolContext], part: int, answer: str) -> bool:
    if part not in (1, 2):
        raise ValueError("part must be 1 or 2")

    stored_result = _check_stored_answer(ctx.deps, part, answer)
    if stored_result is not None:
        is_correct = stored_result
    else:
        client = get_aoc_client()
        response_html = client.submit_answer(ctx.deps.year, ctx.deps.day, part, answer)
        is_correct = _parse_submit_response(response_html)

    if is_correct:
        if part == 1:
            ctx.deps.solve_status.part1_solved = True
        else:
            ctx.deps.solve_status.part2_solved = True

    return is_correct
