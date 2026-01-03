import asyncio

import logfire
import typer

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.core.models import SolutionError, SolutionOutput
from aoc_agent.core.settings import get_settings
from aoc_agent.solver import _create_context, run_agent

logfire.configure()
logfire.instrument_pydantic_ai()
app = typer.Typer()


def _solve_day(year: int, day: int, offline: bool = False) -> None:
    settings = get_settings()
    service = get_aoc_data_service(offline=offline)

    answers = service.get_answers(year, day)
    if not offline and answers.part1 and answers.part2:
        typer.echo(f"   ✅ Day {day} already solved")
        return

    try:
        data = service.get(year, day)
        context = _create_context(year, day, data, offline=offline)
        result = asyncio.run(run_agent(settings, context, model=settings.model))

        if isinstance(result, SolutionOutput):
            typer.echo(f"   🎉 Day {day} solved! P1={result.part1} P2={result.part2}")
        elif isinstance(result, SolutionError):
            typer.echo(f"   ⚠️  Day {day} error: {result.error}")
            if result.partial_part1:
                typer.echo(f"      Partial Part 1: {result.partial_part1}")
            if result.partial_part2:
                typer.echo(f"      Partial Part 2: {result.partial_part2}")
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
    if day is None:
        _solve_year(year, offline=False)
    else:
        _solve_day(year, day, offline=False)


@app.command()
def test(
    year: int = typer.Argument(help="Year"),
    day: int | None = typer.Argument(default=None, help="Day (omit to test entire year)"),
) -> None:
    if day is None:
        _solve_year(year, offline=True)
    else:
        _solve_day(year, day, offline=True)


def main() -> None:
    app()
