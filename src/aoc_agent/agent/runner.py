import logfire
from opentelemetry import trace
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.adapters.execution.jupyter import jupyter_context
from aoc_agent.agent.factory import create_agent
from aoc_agent.agent.prompts import build_agent_prompt
from aoc_agent.core.constants import OutputMode
from aoc_agent.core.models import AgentRunResult
from aoc_agent.tools.context import ToolContext


def _get_trace_id() -> str:
    current_span = trace.get_current_span()
    span_context = current_span.get_span_context()
    return f"{span_context.trace_id:032x}"


async def run_agent(  # noqa: PLR0913
    model: Model,
    context: ToolContext,
    model_name: str,
    *,
    allow_sleep: bool = True,
    run_usage: RunUsage | None = None,
    output_mode: OutputMode = OutputMode.TOOL,
) -> AgentRunResult:
    service = get_aoc_data_service(offline=context.offline)
    data = service.get(context.year, context.day)
    prompt = build_agent_prompt(
        problem_html=data.problem_html.unsolved_html,
        day=context.day,
        allow_sleep=allow_sleep,
    )
    agent = create_agent(model, allow_sleep=allow_sleep, output_mode=output_mode)
    async with jupyter_context(context) as context_with_kernel, agent:
        with logfire.span(
            "solve {year}/day{day}",
            year=context_with_kernel.year,
            day=context_with_kernel.day,
            model=model_name,
        ):
            trace_id = _get_trace_id()
            result = await agent.run(prompt, deps=context_with_kernel, usage=run_usage)
    return AgentRunResult(
        output=result.output,
        trace_id=trace_id,
    )
