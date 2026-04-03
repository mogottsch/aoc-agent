from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Split(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    HOLDOUT = "holdout"
    UNASSIGNED = "unassigned"


class Difficulty(StrEnum):
    UNKNOWN = "unknown"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class AocTaskRecord(BaseModel):
    year: int = Field(ge=2015)
    day: int = Field(ge=1, le=25)
    split: Split = Split.UNASSIGNED
    estimated_difficulty: Difficulty = Difficulty.UNKNOWN
    has_unsolved_html: bool
    has_part1_solved_html: bool
    has_part2_solved_html: bool
    has_input: bool
    has_answers: bool
    cache_dir: Path
    unsolved_html_path: Path | None = None
    part1_solved_html_path: Path | None = None
    part2_solved_html_path: Path | None = None
    input_path: Path | None = None
    notes: str | None = None

    @property
    def is_runnable(self) -> bool:
        return self.has_unsolved_html and self.has_input
