from pydantic import BaseModel


class ToolContext(BaseModel):
    year: int
    day: int
    input_content: str
    session_token: str
    part1_answer: str | None = None
    part2_answer: str | None = None
