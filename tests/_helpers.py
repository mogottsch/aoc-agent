from dataclasses import dataclass
from typing import cast

from pydantic_ai import RunContext

from aoc_agent.tools.context import ToolContext


@dataclass(slots=True)
class FakeRunContext:
    deps: ToolContext


def as_run_context(deps: ToolContext) -> RunContext[ToolContext]:
    return cast(RunContext[ToolContext], FakeRunContext(deps))
