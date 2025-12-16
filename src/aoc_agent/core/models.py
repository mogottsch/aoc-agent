from pydantic import BaseModel

Answer = int | str


class Answers(BaseModel):
    part1: Answer | None = None
    part2: Answer | None = None


class SolveStatus(BaseModel):
    part1_solved: bool = False
    part2_solved: bool = False


class SolutionOutput(BaseModel):
    part1: Answer
    part2: Answer


class SolutionError(BaseModel):
    error: str
    partial_part1: Answer | None = None
    partial_part2: Answer | None = None


SolverResult = SolutionOutput | SolutionError
