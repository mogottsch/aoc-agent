from pydantic import BaseModel

from aoc_agent.core.models import SolveStatus


class ToolContext(BaseModel):
    year: int
    day: int
    input_content: str
    solve_status: SolveStatus
