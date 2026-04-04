import json
from pathlib import Path

from pydantic import BaseModel

from aoc_agent.adapters.storage.data_store import AOCDataStore


class AocPrimeDatasetInfo(BaseModel):
    year: int
    day: int
    input_content: str
    unsolved_html: str
    part1_solved_html: str
    part2_solved_html: str


class AocPrimeDatasetRow(BaseModel):
    task: str = "aoc_prime_env"
    info: AocPrimeDatasetInfo


def export_prime_dataset(
    cache_dir: Path = Path("cache"), output: Path = Path("data/aoc-prime.jsonl")
) -> int:
    store = AOCDataStore(cache_dir)
    rows: list[AocPrimeDatasetRow] = []
    if not cache_dir.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("")
        return 0
    for year_dir in sorted(
        path for path in cache_dir.iterdir() if path.is_dir() and path.name.isdigit()
    ):
        year = int(year_dir.name)
        for day in range(1, 26):
            data = store.get(year, day)
            if data is None:
                continue
            part1 = data.problem_html.part1_solved_html
            part2 = data.problem_html.part2_solved_html
            if part1 is None or part2 is None:
                continue
            rows.append(
                AocPrimeDatasetRow(
                    info=AocPrimeDatasetInfo(
                        year=year,
                        day=day,
                        input_content=data.input_content,
                        unsolved_html=data.problem_html.unsolved_html,
                        part1_solved_html=part1,
                        part2_solved_html=part2,
                    )
                )
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row.model_dump()) + "\n")
    return len(rows)
