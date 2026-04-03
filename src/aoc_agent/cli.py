import asyncio
import os
from pathlib import Path
from typing import Annotated

import logfire
import typer
from rich.traceback import install as install_rich_traceback

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.adapters.model_factory import create_model
from aoc_agent.adapters.models import list_available_models, models_as_json, resolve_provider_target
from aoc_agent.agent.runner import run_agent
from aoc_agent.benchmark.config import load_config
from aoc_agent.benchmark.report import generate_report
from aoc_agent.benchmark.results import migrate_legacy_results
from aoc_agent.benchmark.runner import run_benchmark
from aoc_agent.core.constants import DAY_25
from aoc_agent.core.models import SolutionError, SolutionOutput, SolveStatus
from aoc_agent.core.settings import get_settings
from aoc_agent.prime_cli import (
    PrimeEvalConfig,
    PrimeRolloutConfig,
    PrimeToolChoiceMode,
    build_prime_sampling_args,
    load_prime_environment,
    load_prime_eval_config,
    load_prime_rollout_config,
    make_prime_client_config,
)
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
        model = create_model(
            model_name=settings.model,
            base_url=settings.api_base_url,
            api_key=settings.get_api_key(),
            disable_tool_choice=settings.disable_tool_choice,
        )
        agent_result = asyncio.run(
            run_agent(model, context, model_name=settings.model, output_mode=settings.output_mode)
        )

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


def _ensure_prime_api_key_from_settings() -> None:
    settings = get_settings()
    if not os.environ.get("PRIME_API_KEY") and settings.prime_api_key:
        os.environ["PRIME_API_KEY"] = settings.prime_api_key


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
) -> None:
    _configure_logfire(console=False)
    benchmark_config = load_config(config)
    results_dir = Path("results")
    asyncio.run(run_benchmark(benchmark_config, results_dir))


@app.command()
def models(
    provider: Annotated[
        str | None, typer.Option(help="Named provider from benchmark config")
    ] = None,
    config: Annotated[Path, typer.Option(help="Path to benchmark config YAML")] = Path(
        "benchmark.yaml"
    ),
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON output")] = False,
) -> None:
    target = resolve_provider_target(provider, config)
    available_models = list_available_models(target)
    if json_output:
        typer.echo(models_as_json(available_models))
        return
    for model in available_models:
        typer.echo(model.id)


@app.command()
def results() -> None:
    results_dir = Path("results")
    output_path = results_dir / "README.md"
    markdown = generate_report(results_dir)
    output_path.write_text(markdown)
    typer.echo(f"Report written to {output_path}")


@app.command()
def migrate(
    delete: bool = typer.Option(default=False, help="Delete legacy files after migration"),
) -> None:
    results_dir = Path("results")
    count = migrate_legacy_results(results_dir, delete=delete)
    if count == 0:
        typer.echo("No legacy result files found")
    else:
        typer.echo(f"Migrated {count} legacy file(s) into results/results.jsonl")
        if not delete:
            typer.echo("Legacy files kept. Use --delete to remove them.")


@app.command()
def prime_eval(  # noqa: PLR0913
    model: Annotated[str | None, typer.Option(help="Prime hosted model id")] = None,
    config: Annotated[Path | None, typer.Option(help="Path to Prime eval config YAML")] = None,
    cache_dir: Annotated[Path | None, typer.Option(help="Offline AoC cache directory")] = None,
    output: Annotated[Path | None, typer.Option(help="Output JSONL path")] = None,
    num_examples: Annotated[int | None, typer.Option(help="Number of eval examples")] = None,
    rollouts_per_example: Annotated[int | None, typer.Option(help="Rollouts per example")] = None,
    max_concurrent: Annotated[int | None, typer.Option(help="Max concurrent rollouts")] = None,
    max_tokens: Annotated[int | None, typer.Option(help="Sampling max tokens")] = None,
    tool_choice: Annotated[
        PrimeToolChoiceMode | None,
        typer.Option(help="Prime tool_choice mode: required or auto"),
    ] = None,
    year: Annotated[
        int | None, typer.Option(help="Restrict offline dataset to a single AoC year")
    ] = None,
) -> None:
    _ensure_prime_api_key_from_settings()
    file_config = (
        load_prime_eval_config(config) if config is not None else PrimeEvalConfig(model="")
    )
    resolved_model = model or file_config.model
    if not resolved_model:
        raise typer.BadParameter("model is required unless provided via --config")
    resolved_cache_dir = cache_dir or file_config.cache_dir
    resolved_output = output or file_config.output
    resolved_num_examples = num_examples or file_config.num_examples
    resolved_rollouts_per_example = rollouts_per_example or file_config.rollouts_per_example
    resolved_max_concurrent = max_concurrent or file_config.max_concurrent
    resolved_max_tokens = max_tokens or file_config.max_tokens
    resolved_tool_choice = tool_choice or file_config.tool_choice
    resolved_year = year if year is not None else file_config.year

    env = load_prime_environment(cache_dir=resolved_cache_dir, year=resolved_year)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    results = env.evaluate_sync(
        client=make_prime_client_config(),
        model=resolved_model,
        num_examples=resolved_num_examples,
        rollouts_per_example=resolved_rollouts_per_example,
        max_concurrent=resolved_max_concurrent,
        sampling_args=build_prime_sampling_args(
            max_tokens=resolved_max_tokens, tool_choice=resolved_tool_choice
        ),
        results_path=resolved_output,
        save_results=True,
    )
    typer.echo(f"Prime eval complete: {len(results)} rollouts -> {resolved_output}")


@app.command()
def prime_rollout(  # noqa: PLR0913
    model: Annotated[str | None, typer.Option(help="Prime hosted model id")] = None,
    config: Annotated[Path | None, typer.Option(help="Path to Prime rollout config YAML")] = None,
    cache_dir: Annotated[Path | None, typer.Option(help="Offline AoC cache directory")] = None,
    output: Annotated[Path | None, typer.Option(help="Output JSONL path")] = None,
    max_concurrent: Annotated[int | None, typer.Option(help="Max concurrent rollouts")] = None,
    max_tokens: Annotated[int | None, typer.Option(help="Sampling max tokens")] = None,
    tool_choice: Annotated[
        PrimeToolChoiceMode | None,
        typer.Option(help="Prime tool_choice mode: required or auto"),
    ] = None,
    year: Annotated[
        int | None, typer.Option(help="Restrict offline dataset to a single AoC year")
    ] = None,
) -> None:
    _ensure_prime_api_key_from_settings()
    file_config = (
        load_prime_rollout_config(config) if config is not None else PrimeRolloutConfig(model="")
    )
    resolved_model = model or file_config.model
    if not resolved_model:
        raise typer.BadParameter("model is required unless provided via --config")
    resolved_cache_dir = cache_dir or file_config.cache_dir
    resolved_output = output or file_config.output
    resolved_max_concurrent = max_concurrent or file_config.max_concurrent
    resolved_max_tokens = max_tokens or file_config.max_tokens
    resolved_tool_choice = tool_choice or file_config.tool_choice
    resolved_year = year if year is not None else file_config.year

    env = load_prime_environment(cache_dir=resolved_cache_dir, year=resolved_year)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    inputs = list(env.dataset)
    results = env.generate_sync(
        inputs,
        client=make_prime_client_config(),
        model=resolved_model,
        max_concurrent=resolved_max_concurrent,
        sampling_args=build_prime_sampling_args(
            max_tokens=resolved_max_tokens, tool_choice=resolved_tool_choice
        ),
        results_path=resolved_output,
        save_results=True,
    )
    typer.echo(f"Prime rollout complete: {len(results)} rollouts -> {resolved_output}")


@app.command(name="copilot-login")
def copilot_login() -> None:
    from aoc_agent.adapters.copilot.auth import copilot_login as _copilot_login  # noqa: PLC0415

    _copilot_login()
    typer.echo("Copilot auth successful. Token cached.")


def main() -> None:
    app()
