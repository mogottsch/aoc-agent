from bs4 import BeautifulSoup
from pydantic_ai import RunContext

from aoc_agent.adapters.aoc.client import get_aoc_client
from aoc_agent.tools.context import ToolContext


def _check_stored_answer(context: ToolContext, part: int, answer: str) -> str | None:
    stored_answer = context.part1_answer if part == 1 else context.part2_answer
    if not stored_answer:
        return None

    if stored_answer == answer:
        return "Correct! (from stored data)"
    return f"Wrong answer. Correct answer (from stored data): {stored_answer}"


def _parse_submit_response(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")

    if not main:
        return "Error: Could not parse response"

    main_text = main.get_text()

    if "That's the right answer" in main_text or "That's correct" in main_text:
        return "Correct!"
    if "too high" in main_text.lower():
        return "Too high"
    if "too low" in main_text.lower():
        return "Too low"

    return "Wrong answer"


def submit_answer(ctx: RunContext[ToolContext], part: int, answer: str) -> str:
    """Submit an answer for a puzzle part.

    Args:
            part: The part number (1 or 2).
            answer: The answer to submit.

    """
    if part not in (1, 2):
        return "Error: part must be 1 or 2"

    stored_result = _check_stored_answer(ctx.deps, part, answer)
    if stored_result:
        return stored_result

    client = get_aoc_client()
    response_html = client.submit_answer(ctx.deps.year, ctx.deps.day, part, answer)
    return _parse_submit_response(response_html)
