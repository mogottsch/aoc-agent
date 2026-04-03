import json
from pathlib import Path

from aoc_rl.dataset.export import build_task_manifest, write_task_manifest
from aoc_rl.dataset.manifest import Split


def test_build_task_manifest_reads_cached_tasks(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    year_dir = cache_dir / "2022"
    year_dir.mkdir(parents=True)
    (year_dir / "day_1.unsolved.html").write_text("<html>problem</html>")
    (year_dir / "day_1.input.txt").write_text("1\n2\n3\n")
    (year_dir / "day_1.part1_solved.html").write_text("<code>42</code>")

    records = build_task_manifest(cache_dir)

    assert len(records) == 1
    record = records[0]
    assert record.year == 2022
    assert record.day == 1
    assert record.split == Split.VALIDATION
    assert record.unsolved_html_path == year_dir / "day_1.unsolved.html"
    assert record.input_path == year_dir / "day_1.input.txt"
    assert record.part1_solved_html_path == year_dir / "day_1.part1_solved.html"


def test_write_task_manifest_writes_jsonl(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    year_dir = cache_dir / "2023"
    year_dir.mkdir(parents=True)
    (year_dir / "day_5.unsolved.html").write_text("<html>problem</html>")
    (year_dir / "day_5.input.txt").write_text("abc")

    output_path = tmp_path / "manifest.jsonl"
    records = write_task_manifest(output_path, cache_dir)

    assert len(records) == 1
    lines = output_path.read_text().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["year"] == 2023
    assert payload["day"] == 5
    assert payload["split"] == "test"


def test_build_task_manifest_returns_empty_for_missing_cache(tmp_path: Path) -> None:
    assert build_task_manifest(tmp_path / "missing") == []
