import asyncio
from pathlib import Path
from typing import Annotated

import logfire
import typer
from rich.traceback import install as install_rich_traceback

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.agent.factory import create_openai_model
from aoc_agent.agent.runner import run_agent
from aoc_agent.benchmark.config import load_config
from aoc_agent.benchmark.report import generate_report
from aoc_agent.benchmark.runner import run_benchmark
from aoc_agent.core.constants import DAY_25
from aoc_agent.core.models import SolutionError, SolutionOutput, SolveStatus
from aoc_agent.core.settings import get_settings
from aoc_agent.tools.context import ToolContext

app = typer.Typer()


def _configure_logfire(*, console: bool = True) -> None:
    install_rich_traceback(show_locals=False)
    if console:
        logfire.configure()
    else:
        logfire.configure(console=False)
    logfire.instrument_pydantic_ai()


def _solve_day(year: int, day: int, offline: bool = False) -> None:
    settings = get_settings()
    service = get_aoc_data_service(offline=offline)

    answers = service.get_answers(year, day)
    already_solved = bool(answers.part1) if day == DAY_25 else bool(answers.part1 and answers.part2)
    if not offline and already_solved:
        typer.echo(f"   ✅ Day {day} already solved")
        return

    try:
        data = service.get(year, day)
        context = ToolContext(
            year=year,
            day=day,
            input_content=data.input_content,
            solve_status=SolveStatus(),
            offline=offline,
        )
        model = create_openai_model(
            model_name=settings.model,
            base_url=settings.api_base_url,
            api_key=settings.api_key,
            disable_tool_choice=settings.disable_tool_choice,
        )
        agent_result = asyncio.run(run_agent(model, context, model_name=settings.model))

        if isinstance(agent_result.output, SolutionOutput):
            p1, p2 = agent_result.output.part1, agent_result.output.part2
            typer.echo(f"   🎉 Day {day} solved! P1={p1} P2={p2}")
        elif isinstance(agent_result.output, SolutionError):
            typer.echo(f"   ⚠️  Day {day} error: {agent_result.output.error}")
            if agent_result.output.partial_part1:
                typer.echo(f"      Partial Part 1: {agent_result.output.partial_part1}")
            if agent_result.output.partial_part2:
                typer.echo(f"      Partial Part 2: {agent_result.output.partial_part2}")
    except Exception as e:  # noqa: BLE001
        typer.echo(f"   ❌ Day {day} error: {e}")


def _solve_year(year: int, offline: bool = False) -> None:
    typer.echo(f"🎄 {'Testing' if offline else 'Solving'} Advent of Code {year} 🎄")
    typer.echo("=" * 50)

    for day in range(1, 26):
        typer.echo(f"\n📅 Day {day}")
        _solve_day(year, day, offline=offline)

    typer.echo("\n" + "=" * 50)


@app.command()
def solve(
    year: int = typer.Argument(help="Year"),
    day: int | None = typer.Argument(default=None, help="Day (omit to solve entire year)"),
) -> None:
    _configure_logfire(console=True)
    if day is None:
        _solve_year(year, offline=False)
    else:
        _solve_day(year, day, offline=False)


@app.command()
def test(
    year: int = typer.Argument(help="Year"),
    day: int | None = typer.Argument(default=None, help="Day (omit to test entire year)"),
) -> None:
    _configure_logfire(console=True)
    if day is None:
        _solve_year(year, offline=True)
    else:
        _solve_day(year, day, offline=True)


@app.command()
def benchmark(
    config: Annotated[Path, typer.Option(help="Path to benchmark config YAML")] = Path(
        "benchmark.yaml"
    ),
    force: Annotated[bool, typer.Option(help="Force re-run, ignore existing results")] = False,
) -> None:
    _configure_logfire(console=False)
    benchmark_config = load_config(config)
    results_dir = Path("results")
    asyncio.run(run_benchmark(benchmark_config, results_dir, force))


@app.command()
def results() -> None:
    results_dir = Path("results")
    output_path = results_dir / "README.md"
    markdown = generate_report(results_dir)
    output_path.write_text(markdown)
    typer.echo(f"Report written to {output_path}")


def main() -> None:
    app()
