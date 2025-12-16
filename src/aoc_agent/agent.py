import logfire
import typer

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.core.models import SolutionError, SolutionOutput
from aoc_agent.core.settings import get_settings
from aoc_agent.solver import _create_agent, _create_context, run_agent

logfire.configure()
logfire.instrument_pydantic_ai()
app = typer.Typer()


def _solve_day(year: int, day: int) -> None:
    settings = get_settings()
    service = get_aoc_data_service()

    data = service.get(year, day)
    context = _create_context(year, day, data)
    agent = _create_agent(settings)

    result = run_agent(agent, context, model=settings.model)

    if isinstance(result, SolutionOutput):
        typer.echo(f"Part 1: {result.part1}")
        typer.echo(f"Part 2: {result.part2}")
    else:
        typer.echo(f"❌ Error: {result.error}")
        if result.partial_part1:
            typer.echo(f"   Partial Part 1: {result.partial_part1}")
        if result.partial_part2:
            typer.echo(f"   Partial Part 2: {result.partial_part2}")


def _solve_year(year: int) -> None:
    service = get_aoc_data_service()
    settings = get_settings()

    typer.echo(f"🎄 Solving Advent of Code {year} 🎄")
    typer.echo("=" * 50)

    solved_count = 0

    for day in range(1, 26):
        typer.echo(f"\n📅 Day {day}")

        answers = service.get_answers(year, day)
        if answers.part1 and answers.part2:
            typer.echo("   ✅ Already solved")
            solved_count += 1
            continue

        try:
            data = service.get(year, day)
            context = _create_context(year, day, data)
            agent = _create_agent(settings)

            result = run_agent(agent, context, model=settings.model)

            if isinstance(result, SolutionOutput):
                typer.echo(f"   🎉 Solved! P1={result.part1} P2={result.part2}")
                solved_count += 1
            elif isinstance(result, SolutionError):
                typer.echo(f"   ⚠️  {result.error}")
        except Exception as e:  # noqa: BLE001
            typer.echo(f"   ❌ Error: {e}")

    typer.echo("\n" + "=" * 50)
    typer.echo(f"📊 Summary: {solved_count}/25 days solved")


@app.command()
def solve(
    year: int = typer.Argument(help="Year"),
    day: int | None = typer.Argument(default=None, help="Day (omit to solve entire year)"),
) -> None:
    if day is None:
        _solve_year(year)
    else:
        _solve_day(year, day)


def main() -> None:
    app()
