from dataclasses import dataclass
from typing import cast

from pydantic_ai import RunContext

from aoc_agent.tools.context import ToolContext


@dataclass(slots=True)
class _FakeRunContext:
    deps: ToolContext


def as_run_context(deps: ToolContext) -> RunContext[ToolContext]:
    return cast(RunContext[ToolContext], _FakeRunContext(deps))
