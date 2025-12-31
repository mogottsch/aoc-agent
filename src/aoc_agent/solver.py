import logfire
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from aoc_agent.adapters.aoc.models import AOCData
from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.adapters.execution.jupyter import jupyter_context
from aoc_agent.core.models import SolutionError, SolutionOutput, SolverResult, SolveStatus
from aoc_agent.core.settings import Settings
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import execute_python
from aoc_agent.tools.sleep import sleep
from aoc_agent.tools.submit import submit_answer

INITIAL_PROMPT = (
    "Solve this Advent of Code problem.\n\n"
    "Tools:\n"
    "- execute_python: Run Python code\n"
    "- submit: Submit and verify your answer\n"
    "- get_aoc_problem_description: Get updated problem text\n"
    "- sleep: Wait for specified seconds (use when rate limited)\n\n"
    "Instructions:\n"
    "- The real puzzle input is already available in the variable `input_content`.\n"
    "- Variables and imports persist between `execute_python` calls.\n"
    "- Store large data in variables rather than printing everything.\n"
    "- The `execute_python` output is truncated to 2000 characters by default.\n"
    "- You can increase `max_output_length` if you need to see more.\n"
    "- The examples in the problem description are for understanding only, not the actual input.\n"
    "- You must solve both Part 1 and Part 2 before returning.\n"
    "- Use get_aoc_problem_description to see Part 2 after solving Part 1.\n"
    "- If rate limited, use the sleep tool with the suggested wait time, then retry.\n\n"
    "Problem:\n\n{problem_html}"
)


def _create_agent(
    settings: Settings,
) -> Agent[ToolContext, SolverResult]:
    provider = OpenRouterProvider(api_key=settings.openrouter_api_key)
    model = OpenRouterModel(settings.model, provider=provider)
    return Agent[ToolContext, SolverResult](
        model,
        deps_type=ToolContext,
        output_type=[SolutionOutput, SolutionError],
        tools=[execute_python, submit_answer, get_aoc_problem_description, sleep],
    )


def _create_context(year: int, day: int, data: AOCData) -> ToolContext:
    return ToolContext(
        year=year,
        day=day,
        input_content=data.input_content,
        solve_status=SolveStatus(),
    )


async def run_agent(
    settings: Settings,
    context: ToolContext,
    model: str,
) -> SolverResult:
    service = get_aoc_data_service()
    data = service.get(context.year, context.day)
    prompt = INITIAL_PROMPT.format(problem_html=data.problem_html.unsolved_html)
    agent = _create_agent(settings)
    async with jupyter_context(context) as context_with_kernel, agent:
        with logfire.span(
            "solve {year}/day{day}",
            year=context_with_kernel.year,
            day=context_with_kernel.day,
            model=model,
        ):
            result = await agent.run(prompt, deps=context_with_kernel)
    return result.output
