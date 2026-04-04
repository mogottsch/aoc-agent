import json
from enum import StrEnum
from pathlib import Path

from datasets import Dataset
from huggingface_hub import hf_hub_download
from pydantic import BaseModel, Field

from .prompting import build_agent_prompt

TRAIN_MAX_YEAR = 2021
VALIDATION_YEAR = 2022
TEST_YEAR = 2023
DEFAULT_DATASET_REPO = "mogottsch/aoc-prime"
DEFAULT_DATASET_FILE = "aoc-prime.jsonl"


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
    input_content: str
    unsolved_html: str
    part1_solved_html: str
    part2_solved_html: str


class PromptMessage(BaseModel):
    role: str
    content: str


def assign_default_split(year: int) -> Split:
    if year <= TRAIN_MAX_YEAR:
        return Split.TRAIN
    if year == VALIDATION_YEAR:
        return Split.VALIDATION
    if year == TEST_YEAR:
        return Split.TEST
    return Split.HOLDOUT


def with_default_split(record: AocTaskRecord) -> AocTaskRecord:
    if record.split != Split.UNASSIGNED:
        return record
    return record.model_copy(update={"split": assign_default_split(record.year)})


def resolve_dataset_path(dataset_path: str | None, dataset_repo: str, dataset_file: str) -> Path:
    if dataset_path is not None:
        return Path(dataset_path)
    return Path(
        hf_hub_download(
            repo_id=dataset_repo,
            repo_type="dataset",
            filename=dataset_file,
        )
    )


def build_task_manifest(dataset_path: Path) -> list[AocTaskRecord]:
    if not dataset_path.exists():
        return []
    records: list[AocTaskRecord] = []
    with dataset_path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            info = payload["info"]
            records.append(
                with_default_split(
                    AocTaskRecord(
                        year=int(info["year"]),
                        day=int(info["day"]),
                        input_content=str(info["input_content"]),
                        unsolved_html=str(info["unsolved_html"]),
                        part1_solved_html=str(info["part1_solved_html"]),
                        part2_solved_html=str(info["part2_solved_html"]),
                    )
                )
            )
    return records


def build_datasets(dataset_path: Path) -> tuple[Dataset, Dataset | None]:
    train_rows: list[dict[str, object]] = []
    eval_rows: list[dict[str, object]] = []
    for record in build_task_manifest(dataset_path):
        row = {
            "prompt": [
                PromptMessage(
                    role="user",
                    content=build_agent_prompt(
                        problem_html=record.unsolved_html,
                        day=record.day,
                        allow_sleep=False,
                    ),
                ).model_dump()
            ],
            "task": "aoc_prime_env",
            "info": {
                "year": record.year,
                "day": record.day,
                "split": str(record.split),
                "input_content": record.input_content,
                "unsolved_html": record.unsolved_html,
                "part1_solved_html": record.part1_solved_html,
                "part2_solved_html": record.part2_solved_html,
            },
        }
        if str(record.split) == "train":
            train_rows.append(row)
        if str(record.split) in {"validation", "test"}:
            eval_rows.append(row)
    train_ds = Dataset.from_list(train_rows)
    eval_ds = Dataset.from_list(eval_rows) if eval_rows else None
    return train_ds, eval_ds
