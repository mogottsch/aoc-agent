import logfire
from opentelemetry import trace
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage

from aoc_agent.adapters.aoc.models import AOCData
from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.adapters.execution.jupyter import jupyter_context
from aoc_agent.core.models import (
    AgentRunResult,
    SolutionError,
    SolutionOutput,
    SolverResult,
    SolveStatus,
)
from aoc_agent.core.settings import Settings
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import execute_python
from aoc_agent.tools.sleep import sleep
from aoc_agent.tools.submit import submit_answer


def _build_prompt(*, problem_html: str, allow_sleep: bool) -> str:
    tools: list[str] = ["- execute_python: Run Python code"]
    tools.append("- submit: Submit and verify your answer")
    tools.append("- get_aoc_problem_description: Get updated problem text")
    if allow_sleep:
        tools.append("- sleep: Wait for specified seconds (use when rate limited)")

    instructions: list[str] = [
        "- The real puzzle input is already available in the variable `input_content`.",
        "- Variables and imports persist between `execute_python` calls.",
        "- Store large data in variables rather than printing everything.",
        "- The `execute_python` output is truncated to 2000 characters by default.",
        "- You can increase `max_output_length` if you need to see more.",
        "- Each `execute_python` call has a wall-clock timeout via `timeout_seconds` (default 30s).",  # noqa: E501
        "- The examples in the problem description are for understanding only, not the actual input.",  # noqa: E501
        "- You must solve both Part 1 and Part 2 before returning.",
        "- Use get_aoc_problem_description to see Part 2 after submitting Part 1.",
    ]
    if allow_sleep:
        instructions.append(
            "- If rate limited, use the sleep tool with the suggested wait time, then retry."
        )

    tools_block = "\n".join(tools)
    instructions_block = "\n".join(instructions)
    return (
        "Solve this Advent of Code problem.\n\n"
        f"Tools:\n{tools_block}\n\n"
        f"Instructions:\n{instructions_block}\n\n"
        f"Problem:\n\n{problem_html}"
    )


def _create_agent(model: Model, *, allow_sleep: bool) -> Agent[ToolContext, SolverResult]:
    tools = [execute_python, get_aoc_problem_description]
    tools.append(submit_answer)
    if allow_sleep:
        tools.append(sleep)
    return Agent[ToolContext, SolverResult](
        model,
        deps_type=ToolContext,
        output_type=[SolutionOutput, SolutionError],
        tools=tools,
    )


def create_model_from_settings(settings: Settings) -> OpenAIChatModel:
    provider = OpenAIProvider(
        base_url=settings.api_base_url,
        api_key=settings.api_key,
    )
    return OpenAIChatModel(settings.model, provider=provider)


def _create_context(year: int, day: int, data: AOCData, offline: bool = False) -> ToolContext:
    return ToolContext(
        year=year,
        day=day,
        input_content=data.input_content,
        solve_status=SolveStatus(),
        offline=offline,
    )


def _get_trace_id() -> str:
    current_span = trace.get_current_span()
    span_context = current_span.get_span_context()
    return f"{span_context.trace_id:032x}"


async def run_agent(
    model: Model,
    context: ToolContext,
    model_name: str,
    *,
    allow_sleep: bool = True,
    run_usage: RunUsage | None = None,
) -> AgentRunResult:
    service = get_aoc_data_service(offline=context.offline)
    data = service.get(context.year, context.day)
    prompt = _build_prompt(
        problem_html=data.problem_html.unsolved_html,
        allow_sleep=allow_sleep,
    )
    agent = _create_agent(model, allow_sleep=allow_sleep)
    async with jupyter_context(context) as context_with_kernel, agent:
        with logfire.span(
            "solve {year}/day{day}",
            year=context_with_kernel.year,
            day=context_with_kernel.day,
            model=model_name,
        ):
            trace_id = _get_trace_id()
            result = await agent.run(prompt, deps=context_with_kernel, usage=run_usage)
    usage = run_usage if run_usage is not None else result.usage()
    return AgentRunResult(
        output=result.output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        trace_id=trace_id,
    )
