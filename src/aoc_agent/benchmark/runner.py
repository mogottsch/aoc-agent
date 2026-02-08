import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.usage import RunUsage
from rich.console import Console
from rich.live import Live

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.benchmark.config import BenchmarkConfig, ModelConfig, ProviderConfig
from aoc_agent.benchmark.execution import create_benchmark_result, execute_benchmark
from aoc_agent.benchmark.progress import ProgressTracker
from aoc_agent.benchmark.results import (
    ResultKey,
    append_result,
    get_result_path,
    load_results,
)
from aoc_agent.core.constants import OutputMode
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
    provider_name: str
    semaphore: asyncio.Semaphore
    disable_tool_choice: bool
    openrouter_provider: str | None
    output_mode: OutputMode


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
        agent_result = await execute_benchmark(
            model_id,
            run_config.provider,
            run_config.provider_name,
            tool_context,
            run_usage,
            disable_tool_choice=run_config.disable_tool_choice,
            openrouter_provider=run_config.openrouter_provider,
            output_mode=run_config.output_mode,
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
        agent_result=agent_result,
        duration_seconds=duration,
        output_mode=run_config.output_mode,
        disable_tool_choice=run_config.disable_tool_choice,
    )

    output_path = get_result_path(ctx.results_dir)
    append_result(output_path, result)
    ctx.progress.record_result(model_id, saved=True)
    ctx.live.update(ctx.progress.build_table())


async def run_benchmark(
    config: BenchmarkConfig,
    results_dir: Path,
) -> None:
    console = Console()
    console.print("[bold]Starting benchmark[/bold]")

    result_path = get_result_path(results_dir)
    existing = load_results(result_path)

    all_tasks: list[tuple[ModelConfig, int, int]] = []
    skipped = 0

    for mc in config.models:
        for year in config.years:
            for day in range(1, 26):
                key = ResultKey(
                    model=mc.model,
                    year=year,
                    day=day,
                    output_mode=mc.output_mode,
                    disable_tool_choice=mc.disable_tool_choice,
                )
                if key in existing:
                    skipped += 1
                else:
                    all_tasks.append((mc, year, day))

    console.print(f"Skipped (already done): {skipped}")
    console.print(f"Remaining tasks: {len(all_tasks)}")

    if not all_tasks:
        console.print("[green]Nothing to do![/green]")
        return

    task_counts = Counter(mc.model for mc, _, _ in all_tasks)
    progress = ProgressTracker()
    for model_id, count in task_counts.items():
        progress.init_model(model_id, count)

    model_configs: dict[str, ModelRunConfig] = {}
    for mc in config.models:
        parallelism = mc.parallelism if mc.parallelism is not None else config.per_model_parallelism
        model_configs[mc.model] = ModelRunConfig(
            provider=config.providers[mc.provider],
            provider_name=mc.provider,
            semaphore=asyncio.Semaphore(parallelism),
            disable_tool_choice=mc.disable_tool_choice,
            openrouter_provider=mc.openrouter_provider,
            output_mode=mc.output_mode,
        )

    global_semaphore = (
        asyncio.Semaphore(config.global_parallelism)
        if config.global_parallelism is not None
        else None
    )

    with Live(progress.build_table(), console=console, refresh_per_second=4) as live:
        ctx = BenchmarkContext(results_dir, progress, live)

        async def run_task(mc: ModelConfig, year: int, day: int) -> None:
            run_config = model_configs[mc.model]
            if global_semaphore is not None:
                async with run_config.semaphore, global_semaphore:
                    await _run_single(mc.model, run_config, year, day, ctx)
            else:
                async with run_config.semaphore:
                    await _run_single(mc.model, run_config, year, day, ctx)

        await asyncio.gather(*[run_task(mc, y, d) for mc, y, d in all_tasks])

    console.print(f"\n[bold green]Benchmark complete![/bold green] Results saved to: {results_dir}")
