from pathlib import Path

from aoc_agent.adapters.storage.data_store import AOCDataStore
from aoc_rl.dataset.manifest import AocTaskRecord
from aoc_rl.dataset.splits import with_default_split


def _year_dirs(cache_dir: Path) -> list[Path]:
    if not cache_dir.exists():
        return []
    return sorted(path for path in cache_dir.iterdir() if path.is_dir() and path.name.isdigit())


def _get_paths(cache_dir: Path, year: int, day: int) -> tuple[Path, Path, Path, Path]:
    year_dir = cache_dir / str(year)
    unsolved_path = year_dir / f"day_{day}.unsolved.html"
    part1_path = year_dir / f"day_{day}.part1_solved.html"
    part2_path = year_dir / f"day_{day}.part2_solved.html"
    input_path = year_dir / f"day_{day}.input.txt"
    return unsolved_path, part1_path, part2_path, input_path


def _build_record(store: AOCDataStore, year: int, day: int) -> AocTaskRecord:
    unsolved_path, part1_path, part2_path, input_path = _get_paths(store.data_dir, year, day)
    record = AocTaskRecord(
        year=year,
        day=day,
        has_unsolved_html=unsolved_path.exists(),
        has_part1_solved_html=part1_path.exists(),
        has_part2_solved_html=part2_path.exists(),
        has_input=input_path.exists(),
        has_answers=part1_path.exists() or part2_path.exists(),
        cache_dir=store.data_dir,
        unsolved_html_path=unsolved_path if unsolved_path.exists() else None,
        part1_solved_html_path=part1_path if part1_path.exists() else None,
        part2_solved_html_path=part2_path if part2_path.exists() else None,
        input_path=input_path if input_path.exists() else None,
    )
    return with_default_split(record)


def build_task_manifest(cache_dir: Path = Path("cache")) -> list[AocTaskRecord]:
    store = AOCDataStore(cache_dir)
    records: list[AocTaskRecord] = []
    for year_dir in _year_dirs(cache_dir):
        year = int(year_dir.name)
        for day in range(1, 26):
            record = _build_record(store, year, day)
            if record.has_unsolved_html or record.has_input:
                records.append(record)
    return records


def write_task_manifest(output_path: Path, cache_dir: Path = Path("cache")) -> list[AocTaskRecord]:
    records = build_task_manifest(cache_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")
    return records
