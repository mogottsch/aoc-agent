from bs4 import BeautifulSoup
from pydantic import BaseModel
from pydantic_ai import RunContext

from aoc_agent.adapters.aoc.client import get_aoc_client
from aoc_agent.tools.context import ToolContext


class SubmitResult(BaseModel):
    correct: bool
    message: str


def _extract_answer_from_html(html: str, part: int) -> int | str | None:
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.find_all("article", class_="day-desc")
    article_index = part - 1

    if len(articles) <= article_index:
        return None

    answer_tag = articles[article_index].find_next_sibling("p")
    if not answer_tag or "Your puzzle answer was" not in str(answer_tag):
        return None

    code_tag = answer_tag.find("code")
    if not code_tag:
        return None

    text = code_tag.get_text()
    try:
        return int(text)
    except ValueError:
        return text


def _check_stored_answer(context: ToolContext, part: int, answer: int | str) -> bool | None:
    stored = context.answers.part1 if part == 1 else context.answers.part2
    if stored is None:
        return None
    return stored == answer


def _parse_submit_response(html: str) -> SubmitResult:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")

    if not main:
        raise ValueError("Could not parse response")

    main_text = main.get_text()

    if "That's the right answer" in main_text or "That's correct" in main_text:
        return SubmitResult(correct=True, message="Correct!")
    if "too high" in main_text.lower():
        return SubmitResult(correct=False, message="Wrong: answer is too high")
    if "too low" in main_text.lower():
        return SubmitResult(correct=False, message="Wrong: answer is too low")
    if "not the right answer" in main_text.lower():
        return SubmitResult(correct=False, message="Wrong answer")
    if "too recently" in main_text.lower():
        return SubmitResult(correct=False, message="Rate limited: wait before submitting again")
    return SubmitResult(correct=False, message="Unknown response")


def _check_already_solved(year: int, day: int, part: int) -> int | str | None:
    client = get_aoc_client()
    html = client.fetch_problem_html(year, day)
    return _extract_answer_from_html(html, part)


def submit_answer(ctx: RunContext[ToolContext], part: int, answer: int | str) -> SubmitResult:
    """Submit an answer for verification. Returns result with correctness and message."""
    if part not in (1, 2):
        raise ValueError("part must be 1 or 2")

    stored_result = _check_stored_answer(ctx.deps, part, answer)
    if stored_result is not None:
        result = SubmitResult(
            correct=stored_result, message="Correct!" if stored_result else "Wrong answer"
        )
    else:
        already_solved = _check_already_solved(ctx.deps.year, ctx.deps.day, part)
        if already_solved is not None:
            is_correct = already_solved == answer
            result = SubmitResult(
                correct=is_correct, message="Correct!" if is_correct else "Wrong answer"
            )
        else:
            client = get_aoc_client()
            response_html = client.submit_answer(ctx.deps.year, ctx.deps.day, part, str(answer))
            result = _parse_submit_response(response_html)

    if result.correct:
        if part == 1:
            ctx.deps.solve_status.part1_solved = True
        else:
            ctx.deps.solve_status.part2_solved = True

    return result
