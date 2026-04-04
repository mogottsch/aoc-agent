from pydantic import BaseModel, Field

from .constants import INCORRECT_SUBMIT_LIMIT

Answer = int | str


class SubmitLimitExceededError(Exception):
    pass


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
            message = (
                f"same incorrect answer submitted {INCORRECT_SUBMIT_LIMIT} times: answer={answer}"
            )
            raise SubmitLimitExceededError(message)


class SolveStatus(BaseModel):
    part1_solved: bool = False
    part2_solved: bool = False
    part1_incorrect_streak: IncorrectSubmitStreak = Field(default_factory=IncorrectSubmitStreak)
    part2_incorrect_streak: IncorrectSubmitStreak = Field(default_factory=IncorrectSubmitStreak)
