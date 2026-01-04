from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class BenchmarkResult(BaseModel):
    model: str
    year: int
    day: int
    part1_correct: bool | None
    part2_correct: bool | None
    duration_seconds: float
    input_tokens: int
    output_tokens: int
    error: str | None
    trace_id: str
    timestamp: datetime


def get_result_path(base_dir: Path, model: str, year: int) -> Path:
    safe_model = model.replace("/", "--").replace(":", "--")
    return base_dir / f"{safe_model}--{year}.jsonl"


def load_results(path: Path) -> dict[int, BenchmarkResult]:
    if not path.exists():
        return {}
    results: dict[int, BenchmarkResult] = {}
    for line in path.read_text().strip().split("\n"):
        if not line:
            continue
        r = BenchmarkResult.model_validate_json(line)
        results[r.day] = r
    return results


def append_result(path: Path, result: BenchmarkResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(result.model_dump_json() + "\n")
