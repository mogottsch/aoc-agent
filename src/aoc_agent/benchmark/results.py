from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class BenchmarkResult(BaseModel):
    model: str
    year: int
    day: int
    part1_correct: bool | None
    part2_correct: bool | None
    duration_seconds: float
    input_tokens: int | None = Field(default=None, exclude=True)
    output_tokens: int | None = Field(default=None, exclude=True)
    reasoning_tokens: int | None = Field(default=None, exclude=True)
    total_cost: float | None = Field(default=None, exclude=True)
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


def load_all_results(results_dir: Path) -> list[BenchmarkResult]:
    if not results_dir.exists():
        return []
    by_key: dict[tuple[str, int, int], BenchmarkResult] = {}
    for jsonl_file in results_dir.glob("*.jsonl"):
        for line in jsonl_file.read_text().strip().split("\n"):
            if not line:
                continue
            r = BenchmarkResult.model_validate_json(line)
            key = (r.model, r.year, r.day)
            if key not in by_key or r.timestamp > by_key[key].timestamp:
                by_key[key] = r
    return list(by_key.values())
