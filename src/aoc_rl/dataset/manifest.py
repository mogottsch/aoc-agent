from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Split(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    HOLDOUT = "holdout"
    UNASSIGNED = "unassigned"


class AocTaskRecord(BaseModel):
    year: int = Field(ge=2015)
    day: int = Field(ge=1, le=25)
    split: Split = Split.UNASSIGNED
    unsolved_html_path: Path
    part1_solved_html_path: Path | None = None
    part2_solved_html_path: Path | None = None
    input_path: Path
