from pydantic import BaseModel, ConfigDict

from aoc_agent.adapters.execution.jupyter_executor import Executor
from aoc_agent.core.models import SolveStatus


class ToolContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    year: int
    day: int
    input_content: str
    solve_status: SolveStatus
    executor: Executor | None = None
    offline: bool = False
