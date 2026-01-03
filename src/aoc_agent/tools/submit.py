from pydantic_ai import RunContext

from aoc_agent.adapters.aoc.client import get_aoc_client
from aoc_agent.adapters.aoc.parser import SubmitResponse, SubmitStatus, parse_submit_response
from aoc_agent.adapters.aoc.service import AOCDataService, get_aoc_data_service
from aoc_agent.core.models import PART_1, PART_2, IncorrectSubmitStreak, SolveStatus
from aoc_agent.tools.context import ToolContext


class SubmitResult(SubmitResponse):
    pass


_SUBMIT_CACHE: dict[tuple[int, int, int, int | str], SubmitResponse] = {}


def _check_known(
    service: AOCDataService, year: int, day: int, part: int, answer: int | str
) -> SubmitResult | None:
    answers = service.get_answers(year, day)
    stored = answers.part1 if part == PART_1 else answers.part2
    if stored is None:
        return None
    status = SubmitStatus.CORRECT if str(stored) == str(answer) else SubmitStatus.INCORRECT
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
    if part == PART_1:
        solve_status.part1_solved = True
    else:
        solve_status.part2_solved = True


def _streak_for_part(solve_status: SolveStatus, part: int) -> IncorrectSubmitStreak:
    return (
        solve_status.part1_incorrect_streak
        if part == PART_1
        else solve_status.part2_incorrect_streak
    )


def _submit_to_aoc_cached(
    service: AOCDataService,
    year: int,
    day: int,
    part: int,
    answer: int | str,
) -> SubmitResult:
    cache_key = (year, day, part, answer)
    cached = _SUBMIT_CACHE.get(cache_key)
    if cached is not None:
        return SubmitResult(
            status=cached.status,
            message=cached.message,
            wait_seconds=cached.wait_seconds,
        )

    result = _submit_to_aoc(service, year, day, part, answer)
    if result.status in {SubmitStatus.CORRECT, SubmitStatus.INCORRECT}:
        _SUBMIT_CACHE[cache_key] = SubmitResponse(
            status=result.status,
            message=result.message,
            wait_seconds=result.wait_seconds,
        )
    return result


def submit_answer(ctx: RunContext[ToolContext], part: int, answer: int | str) -> SubmitResult:
    if part not in (PART_1, PART_2):
        raise ValueError("part must be 1 or 2")

    year, day = ctx.deps.year, ctx.deps.day
    service = get_aoc_data_service(offline=ctx.deps.offline)

    result = _check_known(service, year, day, part, answer)
    if part == PART_2 and not service.is_part_solved(year, day, PART_1):
        return SubmitResult(
            status=SubmitStatus.ERROR,
            message="Part 1 must be solved before submitting Part 2",
        )
    if result is None:
        if ctx.deps.offline:
            return SubmitResult(
                status=SubmitStatus.ERROR,
                message="Cannot submit answer in offline mode: answer is not in cache",
            )
        result = _submit_to_aoc_cached(service, year, day, part, answer)

    incorrect_streak = _streak_for_part(ctx.deps.solve_status, part)
    if result.status == SubmitStatus.CORRECT:
        _mark_solved(ctx.deps.solve_status, part)
        incorrect_streak.reset()
    elif result.status == SubmitStatus.INCORRECT:
        incorrect_streak.record_incorrect(answer)

    return result
