from pathlib import Path
from typing import TypedDict

from datasets import Dataset

from aoc_agent.agent.prompts import build_agent_prompt
from aoc_rl.dataset.export import build_task_manifest
from aoc_rl.dataset.manifest import AocTaskRecord


class PromptMessage(TypedDict):
    role: str
    content: str


class PrimeDatasetInfo(TypedDict):
    year: int
    day: int
    split: str
    input_path: str | None
    unsolved_html_path: str | None


class PrimeDatasetRow(TypedDict):
    prompt: list[PromptMessage]
    answer: str
    task: str
    info: PrimeDatasetInfo
    year: int
    day: int


def _extract_part1_answer(record: AocTaskRecord) -> str:
    path = record.part1_solved_html_path
    if path is None or not path.exists():
        return ""
    html = path.read_text()
    marker = "<code>"
    if marker not in html:
        return ""
    return html.split(marker, 1)[1].split("</code>", 1)[0]


def _build_row(record: AocTaskRecord) -> PrimeDatasetRow:
    problem_html = record.unsolved_html_path.read_text()
    return {
        "prompt": [
            {
                "role": "user",
                "content": build_agent_prompt(
                    problem_html=problem_html,
                    day=record.day,
                    allow_sleep=False,
                ),
            }
        ],
        "answer": _extract_part1_answer(record),
        "task": "aoc_rl",
        "info": {
            "year": record.year,
            "day": record.day,
            "split": str(record.split),
            "input_path": str(record.input_path) if record.input_path else None,
            "unsolved_html_path": str(record.unsolved_html_path)
            if record.unsolved_html_path
            else None,
        },
        "year": record.year,
        "day": record.day,
    }


def build_datasets(cache_dir: Path, year: int | None = None) -> tuple[Dataset, Dataset | None]:
    manifest = build_task_manifest(cache_dir)
    train_rows: list[PrimeDatasetRow] = []
    eval_rows: list[PrimeDatasetRow] = []

    for record in manifest:
        if year is not None and record.year != year:
            continue
        row = _build_row(record)
        train_rows.append(row)
        if str(record.split) in {"validation", "test"}:
            eval_rows.append(row)

    train_ds = Dataset.from_list(train_rows)
    eval_ds = Dataset.from_list(eval_rows) if eval_rows else None
    return train_ds, eval_ds
