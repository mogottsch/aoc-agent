import logfire
import typer
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from aoc_agent.adapters.aoc.fetcher import fetch_aoc_data
from aoc_agent.adapters.storage.data_store import get_data_store
from aoc_agent.core.settings import get_settings
from aoc_agent.tools.context import SolveStatus, ToolContext
from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import execute_python
from aoc_agent.tools.submit import submit_answer

logfire.configure()
logfire.instrument_pydantic_ai()
app = typer.Typer()


@app.command()
def fetch(
    year: int = typer.Argument(help="Year"),
    day: int = typer.Argument(help="Day"),
) -> None:
    store = get_data_store()

    data = fetch_aoc_data(year=year, day=day)
    store.store(year=year, day=day, data=data)

    typer.echo(f"Fetched and stored data for {year}/day {day}")


@app.command()
def solve(
    year: int = typer.Argument(help="Year"),
    day: int = typer.Argument(help="Day"),
) -> None:
    settings = get_settings()
    store = get_data_store()

    if not store.exists(year, day):
        data = fetch_aoc_data(year=year, day=day)
        store.store(year=year, day=day, data=data)
        typer.echo(f"Fetched and stored data for {year}/day {day}")

    data = store.get(year, day)
    if not data:
        message = f"Failed to get data for {year}/day {day}"
        raise RuntimeError(message)

    provider = OpenRouterProvider(api_key=settings.openrouter_api_key)
    model = OpenRouterModel(settings.model, provider=provider)

    answers = store.get_answers(year, day)

    solve_status = SolveStatus(
        part1_solved=False,
        part2_solved=False,
    )

    context = ToolContext(
        year=year,
        day=day,
        input_content=data.input_content,
        session_token=settings.aoc_session_token,
        problem_html=data.problem_html,
        part1_answer=answers.part1,
        part2_answer=answers.part2,
        solve_status=solve_status,
    )

    agent = Agent(
        model,
        deps_type=ToolContext,
        tools=[execute_python, submit_answer, get_aoc_problem_description],
    )

    initial_prompt = (
        "Solve this Advent of Code problem.\n\n"
        "You have the execute tool to run any Python code "
        "(the input is available as 'input_content').\n"
        "You have the submit tool to submit and check your answers.\n\n"
        f"Problem:\n\n{data.problem_html.unsolved_html}"
    )
    message_history = None

    for run_num in range(3):
        if run_num == 0:
            prompt = initial_prompt
        else:
            unsolved_parts = []
            if not context.solve_status.part1_solved:
                unsolved_parts.append("Part 1")
            if not context.solve_status.part2_solved:
                unsolved_parts.append("Part 2")
            unsolved_text = " and ".join(unsolved_parts)
            prompt = (
                f"{unsolved_text} is still unsolved. "
                "Continue and submit your solution via the submit tool."
            )

        result = agent.run_sync(prompt, deps=context, message_history=message_history)
        print(result.output)

        if context.solve_status.part1_solved and context.solve_status.part2_solved:
            break

        message_history = result.new_messages()


def main() -> None:
    app()
