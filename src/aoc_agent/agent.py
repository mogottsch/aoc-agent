from pathlib import Path

import typer
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from aoc_agent.adapters.aoc.fetcher import fetch_aoc_data
from aoc_agent.adapters.storage.cache import FileCache
from aoc_agent.core.settings import get_settings

app = typer.Typer()


@app.command()
def fetch(
    year: int = typer.Argument(help="Year"),
    day: int = typer.Argument(help="Day"),
) -> None:
    settings = get_settings()

    cache_dir = Path("cache")
    cache = FileCache(cache_dir)

    data = fetch_aoc_data(year=year, day=day, session_token=settings.aoc_session_token)
    cache.store(year=year, day=day, data=data)

    typer.echo(f"Fetched and cached data for {year}/day {day}")


@app.command()
def test() -> None:
    settings = get_settings()
    provider = OpenRouterProvider(api_key=settings.openrouter_api_key)
    model = OpenRouterModel("tngtech/deepseek-r1t2-chimera:free", provider=provider)
    agent = Agent(model)
    result = agent.run_sync("Hello")
    print(result.output)


def main() -> None:
    app()
