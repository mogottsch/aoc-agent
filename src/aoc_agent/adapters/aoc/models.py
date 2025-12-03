from pydantic import BaseModel


class ProblemHTML(BaseModel):
    unsolved_html: str
    part1_solved_html: str | None = None
    part2_solved_html: str | None = None


class AOCData(BaseModel):
    problem_html: ProblemHTML
    input_content: str
