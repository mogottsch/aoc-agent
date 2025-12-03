import logfire
import typer
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from aoc_agent.adapters.aoc.fetcher import fetch_aoc_data
from aoc_agent.adapters.storage.cache import get_cache
from aoc_agent.core.settings import get_settings

logfire.configure()
logfire.instrument_pydantic_ai()
app = typer.Typer()


@app.command()
def fetch(
    year: int = typer.Argument(help="Year"),
    day: int = typer.Argument(help="Day"),
) -> None:
    settings = get_settings()
    cache = get_cache()

    data = fetch_aoc_data(year=year, day=day, session_token=settings.aoc_session_token)
    cache.store(year=year, day=day, data=data)

    typer.echo(f"Fetched and cached data for {year}/day {day}")


@app.command()
def solve(
    year: int = typer.Argument(help="Year"),
    day: int = typer.Argument(help="Day"),
) -> None:
    settings = get_settings()
    cache = get_cache()

    if not cache.exists(year, day):
        data = fetch_aoc_data(year=year, day=day, session_token=settings.aoc_session_token)
        cache.store(year=year, day=day, data=data)
        typer.echo(f"Fetched and cached data for {year}/day {day}")

    data = cache.get(year, day)
    if not data:
        message = f"Failed to get data for {year}/day {day}"
        raise RuntimeError(message)

    provider = OpenRouterProvider(api_key=settings.openrouter_api_key)
    model = OpenRouterModel("tngtech/deepseek-r1t2-chimera:free", provider=provider)
    agent = Agent(model)

    prompt = f"Solve this Advent of Code problem:\n\n{data.problem_html.unsolved_html}"
    result = agent.run_sync(prompt)
    print(result.output)


def main() -> None:
    app()
