from pydantic_ai import RunContext

from aoc_agent.adapters.aoc.client import get_aoc_client
from aoc_agent.adapters.aoc.parser import SubmitResponse, SubmitStatus, parse_submit_response
from aoc_agent.adapters.aoc.service import AOCDataService, get_aoc_data_service
from aoc_agent.core.models import IncorrectSubmitStreak, SolveStatus
from aoc_agent.tools.context import ToolContext


class SubmitResult(SubmitResponse):
    pass


def _check_known(
    service: AOCDataService, year: int, day: int, part: int, answer: int | str
) -> SubmitResult | None:
    answers = service.get_answers(year, day)
    stored = answers.part1 if part == 1 else answers.part2
    if stored is None:
        return None
    status = SubmitStatus.CORRECT if stored == answer else SubmitStatus.INCORRECT
    return SubmitResult(status=status)


def _submit_to_aoc(
    service: AOCDataService, year: int, day: int, part: int, answer: int | str
) -> SubmitResult:
    client = get_aoc_client()
    response_html = client.submit_answer(year, day, part, str(answer))
    parsed = parse_submit_response(response_html)
    result = SubmitResult(
        status=parsed.status,
        message=parsed.message,
        wait_seconds=parsed.wait_seconds,
    )
    if result.status == SubmitStatus.CORRECT:
        service.get(year, day)
    return result


def _mark_solved(solve_status: SolveStatus, part: int) -> None:
    if part == 1:
        solve_status.part1_solved = True
    else:
        solve_status.part2_solved = True


def _streak_for_part(solve_status: SolveStatus, part: int) -> IncorrectSubmitStreak:
    return solve_status.part1_incorrect_streak if part == 1 else solve_status.part2_incorrect_streak


def submit_answer(ctx: RunContext[ToolContext], part: int, answer: int | str) -> SubmitResult:
    if part not in (1, 2):
        raise ValueError("part must be 1 or 2")

    year, day = ctx.deps.year, ctx.deps.day
    service = get_aoc_data_service()

    result = _check_known(service, year, day, part, answer) or _submit_to_aoc(
        service, year, day, part, answer
    )

    incorrect_streak = _streak_for_part(ctx.deps.solve_status, part)
    if result.status == SubmitStatus.CORRECT:
        _mark_solved(ctx.deps.solve_status, part)
        incorrect_streak.reset()
    elif result.status == SubmitStatus.INCORRECT:
        incorrect_streak.record_incorrect(answer)

    return result
