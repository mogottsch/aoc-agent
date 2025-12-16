import logfire
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from aoc_agent.adapters.aoc.fetcher import fetch_aoc_data
from aoc_agent.adapters.aoc.models import AOCData
from aoc_agent.adapters.storage.data_store import AOCDataStore
from aoc_agent.core.models import SolutionError, SolutionOutput, SolverResult, SolveStatus
from aoc_agent.core.settings import Settings
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import execute_python
from aoc_agent.tools.submit import submit_answer

INITIAL_PROMPT = (
    "Solve this Advent of Code problem.\n\n"
    "Tools:\n"
    "- execute: Run Python code\n"
    "- submit: Submit and verify your answer\n"
    "- get_aoc_problem_description: Get updated problem text\n\n"
    "Instructions:\n"
    "- The real puzzle input is already available in the variable `input_content`\n"
    "- The examples in the problem description are for understanding only, not the actual input\n"
    "- You must solve both Part 1 and Part 2 before returning\n"
    "- Use get_aoc_problem_description to see Part 2 after solving Part 1\n\n"
    "Problem:\n\n{problem_html}"
)


def _create_agent(settings: Settings) -> Agent[ToolContext, SolverResult]:
    provider = OpenRouterProvider(api_key=settings.openrouter_api_key)
    model = OpenRouterModel(settings.model, provider=provider)
    return Agent[ToolContext, SolverResult](
        model,
        deps_type=ToolContext,
        output_type=[SolutionOutput, SolutionError],
        tools=[execute_python, submit_answer, get_aoc_problem_description],
    )


def _create_context(
    year: int, day: int, data: AOCData, settings: Settings, store: AOCDataStore
) -> ToolContext:
    answers = store.get_answers(year, day)
    return ToolContext(
        year=year,
        day=day,
        input_content=data.input_content,
        session_token=settings.aoc_session_token,
        problem_html=data.problem_html,
        answers=answers,
        solve_status=SolveStatus(),
    )


def ensure_data(year: int, day: int, store: AOCDataStore) -> AOCData:
    if not store.exists(year, day):
        data = fetch_aoc_data(year=year, day=day)
        store.store(year=year, day=day, data=data)

    data = store.get(year, day)
    if not data:
        msg = f"Failed to get data for {year}/day {day}"
        raise RuntimeError(msg)
    return data


def run_agent(
    agent: Agent[ToolContext, SolverResult],
    context: ToolContext,
    model: str,
) -> SolverResult:
    prompt = INITIAL_PROMPT.format(problem_html=context.problem_html.unsolved_html)
    with logfire.span(
        "solve {year}/day{day}",
        year=context.year,
        day=context.day,
        model=model,
    ):
        result = agent.run_sync(prompt, deps=context)
    return result.output
