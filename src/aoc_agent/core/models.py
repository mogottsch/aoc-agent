from pydantic import BaseModel, Field

from aoc_agent.core.constants import INCORRECT_SUBMIT_LIMIT

Answer = int | str


class SubmitLimitExceededError(Exception):
    pass


class Answers(BaseModel):
    part1: Answer | None = None
    part2: Answer | None = None


class IncorrectSubmitStreak(BaseModel):
    answer: Answer | None = None
    count: int = 0

    def reset(self) -> None:
        self.answer = None
        self.count = 0

    def record_incorrect(self, answer: Answer) -> None:
        if self.answer == answer:
            self.count += 1
        else:
            self.answer = answer
            self.count = 1
        if self.count >= INCORRECT_SUBMIT_LIMIT:
            msg = f"same incorrect answer submitted {INCORRECT_SUBMIT_LIMIT} times: answer={answer}"
            raise SubmitLimitExceededError(msg)


class SolveStatus(BaseModel):
    part1_solved: bool = False
    part2_solved: bool = False
    part1_incorrect_streak: IncorrectSubmitStreak = Field(default_factory=IncorrectSubmitStreak)
    part2_incorrect_streak: IncorrectSubmitStreak = Field(default_factory=IncorrectSubmitStreak)


class SolutionOutput(BaseModel):
    part1: Answer
    part2: Answer


class SolutionError(BaseModel):
    error: str
    partial_part1: Answer | None = None
    partial_part2: Answer | None = None


SolverResult = SolutionOutput | SolutionError


class AgentRunResult(BaseModel):
    output: SolverResult
    input_tokens: int
    output_tokens: int
    trace_id: str
