from pydantic import BaseModel

from aoc_agent.adapters.aoc.models import ProblemHTML


class SolveStatus(BaseModel):
    part1_solved: bool
    part2_solved: bool


class ToolContext(BaseModel):
    year: int
    day: int
    input_content: str
    session_token: str
    problem_html: ProblemHTML
    part1_answer: str | None = None
    part2_answer: str | None = None
    solve_status: SolveStatus
