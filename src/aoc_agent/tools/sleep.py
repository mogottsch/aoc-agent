import time

from pydantic_ai import RunContext

from aoc_agent.tools.context import ToolContext


def sleep(_ctx: RunContext[ToolContext], seconds: float) -> None:
    time.sleep(seconds)
