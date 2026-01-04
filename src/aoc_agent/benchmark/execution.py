import json
from datetime import UTC, datetime

import logfire
from opentelemetry import trace
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import RunUsage

from aoc_agent.agent.factory import create_openai_model
from aoc_agent.agent.runner import run_agent
from aoc_agent.benchmark.config import ProviderConfig
from aoc_agent.benchmark.results import BenchmarkResult
from aoc_agent.core.constants import DAY_25
from aoc_agent.core.exceptions import InfrastructureError
from aoc_agent.core.models import (
    SolutionError,
    SolutionOutput,
    SolverResult,
    SubmitLimitExceededError,
)
from aoc_agent.tools.context import ToolContext


def _get_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.trace_id:032x}"


def _check_answer(known: str | int | None, answer: str | None) -> bool | None:
    if known is None or answer is None:
        return None
    return str(known) == answer


def _extract_answers(output: SolverResult) -> tuple[str | None, str | None]:
    if isinstance(output, SolutionOutput):
        return str(output.part1), str(output.part2)
    p1 = str(output.partial_part1) if output.partial_part1 else None
    p2 = str(output.partial_part2) if output.partial_part2 else None
    return p1, p2


def _extract_error(output: SolverResult) -> str | None:
    if isinstance(output, SolutionOutput):
        return None
    return output.error


async def execute_benchmark(  # noqa: C901, PLR0913
    model_id: str,
    provider_config: ProviderConfig,
    tool_context: ToolContext,
    run_usage: RunUsage,
    *,
    disable_tool_choice: bool = False,
    openrouter_provider: str | None = None,
) -> tuple[SolverResult, str]:
    model = create_openai_model(
        model_name=model_id,
        base_url=provider_config.base_url,
        api_key=provider_config.get_api_key(),
        disable_tool_choice=disable_tool_choice,
        openrouter_provider=openrouter_provider,
    )
    trace_id = _get_trace_id()
    try:
        span_name = f"benchmark {model_id} {tool_context.year}/day{tool_context.day}"
        with logfire.span(span_name, model=model_id, year=tool_context.year, day=tool_context.day):
            agent_result = await run_agent(
                model,
                tool_context,
                model_name=model_id,
                allow_sleep=False,
                run_usage=run_usage,
            )
    except SubmitLimitExceededError as e:
        return SolutionError(error=str(e)), trace_id
    except UsageLimitExceeded as e:
        return SolutionError(error=str(e)), trace_id
    except UnexpectedModelBehavior as e:
        return SolutionError(error=str(e)), trace_id
    except ModelHTTPError as e:
        if is_billing_error(e):
            msg = f"Billing/quota error: {e}"
            raise InfrastructureError(msg) from e
        if is_infrastructure_error(e):
            raise InfrastructureError(str(e)) from e
        if e.status_code == 429:  # noqa: PLR2004
            raise InfrastructureError(str(e)) from e
        raise
    except OSError as e:
        if "Too many open files" in str(e):
            raise InfrastructureError(str(e)) from e
        raise
    except json.JSONDecodeError as e:
        msg = f"API returned invalid JSON: {e}"
        raise InfrastructureError(msg) from e
    else:
        return agent_result.output, trace_id


def create_benchmark_result(  # noqa: PLR0913
    model_id: str,
    year: int,
    day: int,
    known_part1: str | int | None,
    known_part2: str | int | None,
    output: SolverResult,
    duration_seconds: float,
    run_usage: RunUsage,
    trace_id: str,
) -> BenchmarkResult:
    part1, part2 = _extract_answers(output)
    error = _extract_error(output)

    part2_correct: bool | None = True if day == DAY_25 else _check_answer(known_part2, part2)

    return BenchmarkResult(
        model=model_id,
        year=year,
        day=day,
        part1_correct=_check_answer(known_part1, part1),
        part2_correct=part2_correct,
        duration_seconds=duration_seconds,
        input_tokens=run_usage.input_tokens,
        output_tokens=run_usage.output_tokens,
        error=error,
        trace_id=trace_id,
        timestamp=datetime.now(tz=UTC),
    )


def is_billing_error(e: ModelHTTPError) -> bool:
    if e.status_code != 429:  # noqa: PLR2004
        return False
    error_str = str(e).lower()
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        code = body.get("code")
        message = str(body.get("message", "")).lower()
        if code == "1113" or "insufficient balance" in message or "recharge" in message:
            return True
    return (
        "insufficient balance" in error_str or "recharge" in error_str or "code': '1113'" in str(e)
    )


def is_infrastructure_error(e: ModelHTTPError) -> bool:
    return e.status_code in {500, 502, 503}
