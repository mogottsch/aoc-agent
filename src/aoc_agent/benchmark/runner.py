import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.usage import RunUsage
from rich.console import Console
from rich.live import Live

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.benchmark.config import BenchmarkConfig, ProviderConfig
from aoc_agent.benchmark.execution import create_benchmark_result, execute_benchmark
from aoc_agent.benchmark.progress import ProgressTracker
from aoc_agent.benchmark.results import (
    append_result,
    get_result_path,
    load_results,
)
from aoc_agent.core.exceptions import InfrastructureError
from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.context import ToolContext


class BenchmarkContext:
    def __init__(self, results_dir: Path, progress: "ProgressTracker", live: Live) -> None:
        self.results_dir = results_dir
        self.progress = progress
        self.live = live


@dataclass
class ModelRunConfig:
    provider: ProviderConfig
    semaphore: asyncio.Semaphore
    disable_tool_choice: bool
    openrouter_provider: str | None


async def _run_single(
    model_id: str,
    run_config: ModelRunConfig,
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
    try:
        output, trace_id = await execute_benchmark(
            model_id,
            run_config.provider,
            tool_context,
            run_usage,
            disable_tool_choice=run_config.disable_tool_choice,
            openrouter_provider=run_config.openrouter_provider,
        )
    except InfrastructureError:
        ctx.progress.record_result(model_id, saved=False)
        ctx.live.update(ctx.progress.build_table())
        return

    duration = time.perf_counter() - start
    result = create_benchmark_result(
        model_id=model_id,
        year=year,
        day=day,
        known_part1=known.part1,
        known_part2=known.part2,
        output=output,
        duration_seconds=duration,
        run_usage=run_usage,
        trace_id=trace_id,
    )

    output_path = get_result_path(ctx.results_dir, model_id, year)
    append_result(output_path, result)
    ctx.progress.record_result(model_id, saved=True)
    ctx.live.update(ctx.progress.build_table())


async def run_benchmark(
    config: BenchmarkConfig,
    results_dir: Path,
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
                if day in existing:
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

    model_configs: dict[str, ModelRunConfig] = {}
    for mc in config.models:
        parallelism = mc.parallelism if mc.parallelism is not None else config.per_model_parallelism
        model_configs[mc.model] = ModelRunConfig(
            provider=config.providers[mc.provider],
            semaphore=asyncio.Semaphore(parallelism),
            disable_tool_choice=mc.disable_tool_choice,
            openrouter_provider=mc.openrouter_provider,
        )

    global_semaphore = (
        asyncio.Semaphore(config.global_parallelism)
        if config.global_parallelism is not None
        else None
    )

    with Live(progress.build_table(), console=console, refresh_per_second=4) as live:
        ctx = BenchmarkContext(results_dir, progress, live)

        async def run_task(model_id: str, year: int, day: int) -> None:
            run_config = model_configs[model_id]
            if global_semaphore is not None:
                async with global_semaphore, run_config.semaphore:
                    await _run_single(model_id, run_config, year, day, ctx)
            else:
                async with run_config.semaphore:
                    await _run_single(model_id, run_config, year, day, ctx)

        await asyncio.gather(*[run_task(m, y, d) for m, y, d in all_tasks])

    console.print(f"\n[bold green]Benchmark complete![/bold green] Results saved to: {results_dir}")
