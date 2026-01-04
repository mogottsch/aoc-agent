import asyncio
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import logfire
from opentelemetry import trace
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import RunUsage
from rich.console import Console
from rich.live import Live

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.benchmark.config import BenchmarkConfig, ProviderConfig, create_model
from aoc_agent.benchmark.progress import ProgressTracker
from aoc_agent.benchmark.results import (
    BenchmarkResult,
    append_result,
    get_result_path,
    load_results,
)
from aoc_agent.core.models import (
    SolutionError,
    SolutionOutput,
    SolverResult,
    SolveStatus,
    SubmitLimitExceededError,
)
from aoc_agent.solver import run_agent
from aoc_agent.tools.context import ToolContext


class BenchmarkContext:
    def __init__(self, results_dir: Path, progress: "ProgressTracker", live: Live) -> None:
        self.results_dir = results_dir
        self.progress = progress
        self.live = live


INFRASTRUCTURE_STATUS_CODES = {429, 500, 502, 503}


class InfrastructureError(Exception):
    pass


def _check_answer(known: str | int | None, answer: str | None) -> bool | None:
    if known is None or answer is None:
        return None
    return str(known) == answer


async def _execute_agent(
    model_id: str,
    provider_config: ProviderConfig,
    tool_context: ToolContext,
    run_usage: RunUsage,
) -> SolverResult:
    model = create_model(model_id, provider_config)
    try:
        agent_result = await run_agent(
            model,
            tool_context,
            model_name=model_id,
            allow_sleep=False,
            run_usage=run_usage,
        )
    except SubmitLimitExceededError as e:
        return SolutionError(error=str(e))
    except UsageLimitExceeded as e:
        return SolutionError(error=str(e))
    except UnexpectedModelBehavior as e:
        return SolutionError(error=str(e))
    except ModelHTTPError as e:
        if e.status_code in INFRASTRUCTURE_STATUS_CODES:
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
        return agent_result.output


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


def _get_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.trace_id:032x}"


async def _run_single(
    model_id: str,
    provider_config: ProviderConfig,
    year: int,
    day: int,
    ctx: BenchmarkContext,
) -> None:
    service = get_aoc_data_service(offline=True)
    known = service.get_answers(year, day)
    data = service.get(year, day)

    tool_context = ToolContext(
        year=year,
        day=day,
        input_content=data.input_content,
        solve_status=SolveStatus(),
        offline=True,
    )

    run_usage = RunUsage()
    start = time.perf_counter()

    with logfire.span("benchmark {model} {year}/day{day}", model=model_id, year=year, day=day):
        trace_id = _get_trace_id()
        try:
            output = await _execute_agent(model_id, provider_config, tool_context, run_usage)
        except InfrastructureError:
            ctx.progress.record_result(model_id, saved=False)
            ctx.live.update(ctx.progress.build_table())
            return

    duration = time.perf_counter() - start
    part1, part2 = _extract_answers(output)
    error = _extract_error(output)

    result = BenchmarkResult(
        model=model_id,
        year=year,
        day=day,
        part1_correct=_check_answer(known.part1, part1),
        part2_correct=_check_answer(known.part2, part2),
        duration_seconds=duration,
        input_tokens=run_usage.input_tokens,
        output_tokens=run_usage.output_tokens,
        error=error,
        trace_id=trace_id,
        timestamp=datetime.now(tz=UTC),
    )

    output_path = get_result_path(ctx.results_dir, model_id, year)
    append_result(output_path, result)
    ctx.progress.record_result(model_id, saved=True)
    ctx.live.update(ctx.progress.build_table())


async def run_benchmark(
    config: BenchmarkConfig,
    results_dir: Path,
    force: bool = False,
) -> None:
    console = Console()
    console.print("[bold]Starting benchmark[/bold]")

    all_tasks: list[tuple[str, int, int]] = []
    skipped = 0

    for mc in config.models:
        for year in config.years:
            result_path = get_result_path(results_dir, mc.model, year)
            existing = load_results(result_path)

            for day in range(1, 26):
                if day in existing and not force:
                    skipped += 1
                else:
                    all_tasks.append((mc.model, year, day))

    console.print(f"Skipped (already done): {skipped}")
    console.print(f"Remaining tasks: {len(all_tasks)}")

    if not all_tasks:
        console.print("[green]Nothing to do![/green]")
        return

    task_counts = Counter(model_id for model_id, _, _ in all_tasks)
    progress = ProgressTracker()
    for model_id, count in task_counts.items():
        progress.init_model(model_id, count)

    semaphores: dict[str, asyncio.Semaphore] = {}
    providers: dict[str, ProviderConfig] = {}
    for mc in config.models:
        parallelism = mc.parallelism if mc.parallelism is not None else config.parallelism
        semaphores[mc.model] = asyncio.Semaphore(parallelism)
        providers[mc.model] = config.providers[mc.provider]

    with Live(progress.build_table(), console=console, refresh_per_second=4) as live:
        ctx = BenchmarkContext(results_dir, progress, live)

        async def run_task(model_id: str, year: int, day: int) -> None:
            async with semaphores[model_id]:
                await _run_single(model_id, providers[model_id], year, day, ctx)

        await asyncio.gather(*[run_task(m, y, d) for m, y, d in all_tasks])

    console.print(f"\n[bold green]Benchmark complete![/bold green] Results saved to: {results_dir}")
