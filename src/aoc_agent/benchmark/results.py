from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel

from aoc_agent.core.constants import OutputMode

RESULTS_FILENAME = "results.jsonl"


class ResultKey(NamedTuple):
    model: str
    year: int
    day: int
    output_mode: OutputMode
    disable_tool_choice: bool


class BenchmarkResult(BaseModel):
    model: str
    year: int
    day: int
    output_mode: OutputMode = OutputMode.TOOL
    disable_tool_choice: bool = False
    part1_correct: bool | None
    part2_correct: bool | None
    duration_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_cost: float | None = None
    error: str | None
    trace_id: str
    timestamp: datetime

    @property
    def key(self) -> ResultKey:
        return ResultKey(
            model=self.model,
            year=self.year,
            day=self.day,
            output_mode=self.output_mode,
            disable_tool_choice=self.disable_tool_choice,
        )


def get_result_path(base_dir: Path) -> Path:
    return base_dir / RESULTS_FILENAME


def _load_from_file(path: Path, by_key: dict[ResultKey, BenchmarkResult]) -> None:
    if not path.exists():
        return
    for line in path.read_text().strip().split("\n"):
        if not line:
            continue
        r = BenchmarkResult.model_validate_json(line)
        if r.key not in by_key or r.timestamp > by_key[r.key].timestamp:
            by_key[r.key] = r


def load_results(path: Path) -> dict[ResultKey, BenchmarkResult]:
    by_key: dict[ResultKey, BenchmarkResult] = {}
    _load_from_file(path, by_key)
    return by_key


def append_result(path: Path, result: BenchmarkResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(result.model_dump_json() + "\n")


def load_all_results(results_dir: Path) -> list[BenchmarkResult]:
    path = get_result_path(results_dir)
    return list(load_results(path).values())


def migrate_legacy_results(results_dir: Path, *, delete: bool = False) -> int:
    result_path = get_result_path(results_dir)
    legacy_files = [f for f in results_dir.glob("*.jsonl") if f.name != RESULTS_FILENAME]
    if not legacy_files:
        return 0

    by_key: dict[ResultKey, BenchmarkResult] = {}
    _load_from_file(result_path, by_key)
    for legacy_file in legacy_files:
        _load_from_file(legacy_file, by_key)

    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("w") as f:
        for r in sorted(by_key.values(), key=lambda r: (r.model, r.year, r.day)):
            f.write(r.model_dump_json() + "\n")

    if delete:
        for legacy_file in legacy_files:
            legacy_file.unlink()

    return len(legacy_files)
