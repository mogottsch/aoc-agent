from pydantic import BaseModel, ConfigDict

from aoc_agent.core.models import SolveStatus


class ToolContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    year: int
    day: int
    input_content: str
    solve_status: SolveStatus
    kernel_manager: object | None = None
    kernel_client: object | None = None
