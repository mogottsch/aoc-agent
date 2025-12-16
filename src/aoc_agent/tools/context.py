from pydantic import BaseModel

from aoc_agent.adapters.aoc.models import ProblemHTML
from aoc_agent.core.models import Answers, SolveStatus


class ToolContext(BaseModel):
    year: int
    day: int
    input_content: str
    session_token: str
    problem_html: ProblemHTML
    answers: Answers
    solve_status: SolveStatus
