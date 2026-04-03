from typing import Any

from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.models import Model

from aoc_agent.core.constants import OutputMode
from aoc_agent.core.models import SolutionError, SolutionOutput, SolverResult
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.description import get_aoc_problem_description
from aoc_agent.tools.execute import execute_python
from aoc_agent.tools.sleep import sleep
from aoc_agent.tools.submit import submit_answer


def _build_output_type(output_mode: OutputMode) -> Any:  # noqa: ANN401
    types = [SolutionOutput, SolutionError]
    if output_mode == OutputMode.TOOL:
        return [ToolOutput(t) for t in types]
    if output_mode == OutputMode.NATIVE:
        return NativeOutput(types)
    return PromptedOutput(types)


def create_agent(
    model: Model,
    *,
    allow_sleep: bool,
    output_mode: OutputMode = OutputMode.TOOL,
) -> Agent[ToolContext, SolverResult]:
    tools = [execute_python, get_aoc_problem_description, submit_answer]
    if allow_sleep:
        tools.append(sleep)
    return Agent[ToolContext, SolverResult](
        model,
        deps_type=ToolContext,
        output_type=_build_output_type(output_mode),
        tools=tools,
    )
