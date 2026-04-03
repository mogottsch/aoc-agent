import json
from pathlib import Path

from datasets import Dataset

from aoc_rl.dataset.export import build_task_manifest


def _load_results(results_path: Path) -> dict[tuple[int, int], dict]:
    if not results_path.exists():
        return {}
    rows: dict[tuple[int, int], dict] = {}
    for line in results_path.read_text().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        key = (int(payload["year"]), int(payload["day"]))
        rows[key] = payload
    return rows


def build_datasets(cache_dir: Path, results_path: Path, year: int | None = None) -> tuple[Dataset, Dataset | None]:
    manifest = build_task_manifest(cache_dir)
    results = _load_results(results_path)
    train_rows: list[dict] = []
    eval_rows: list[dict] = []

    for record in manifest:
        if year is not None and record.year != year:
            continue
        if not record.is_runnable:
            continue
        answers = None
        if record.part1_solved_html_path and record.part1_solved_html_path.exists():
            html = record.part1_solved_html_path.read_text()
            marker = "<code>"
            if marker in html:
                answers = html.split(marker, 1)[1].split("</code>", 1)[0]
        baseline = results.get((record.year, record.day), {})
        row = {
            "prompt": [{"role": "user", "content": f"Solve Advent of Code {record.year} day {record.day}."}],
            "answer": answers or "",
            "task": "aoc_rl",
            "info": {
                "year": record.year,
                "day": record.day,
                "split": str(record.split),
                "prompt_version": "v1",
                "input_path": str(record.input_path) if record.input_path else None,
                "unsolved_html_path": str(record.unsolved_html_path) if record.unsolved_html_path else None,
            },
            "year": record.year,
            "day": record.day,
            "baseline_part1_correct": bool(baseline.get("part1_correct", False)),
            "baseline_part2_correct": bool(baseline.get("part2_correct", False)),
        }
        train_rows.append(row)
        if str(record.split) in {"validation", "test"}:
            eval_rows.append(row)

    train_ds = Dataset.from_list(train_rows)
    eval_ds = Dataset.from_list(eval_rows) if eval_rows else None
    return train_ds, eval_ds
