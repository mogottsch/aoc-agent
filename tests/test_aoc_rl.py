import json
from pathlib import Path

from aoc_rl.dataset.export import build_task_manifest, write_task_manifest
from aoc_rl.dataset.manifest import Split
from aoc_rl.logging.events import (
    EpisodeFinishedEvent,
    EpisodeStartedEvent,
    RewardEvent,
)
from aoc_rl.logging.trajectory import EpisodeTrace, JsonlTrajectoryLogger


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
    assert record.has_unsolved_html is True
    assert record.has_input is True
    assert record.has_answers is True
    assert record.is_runnable is True


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


def test_jsonl_trajectory_logger_appends_episode(tmp_path: Path) -> None:
    logger = JsonlTrajectoryLogger(tmp_path / "trajectories")
    episode = EpisodeTrace(
        model="test-model",
        year=2022,
        day=1,
        prompt_version="v1",
        events=[
            EpisodeStartedEvent(
                step_index=0, model="test-model", year=2022, day=1, prompt_version="v1"
            ),
            RewardEvent(step_index=1, reward=1.0, source="part1_correct"),
            EpisodeFinishedEvent(
                step_index=2,
                solved_part1=True,
                solved_part2=False,
                total_reward=1.0,
                termination_reason="completed",
            ),
        ],
    )

    path = logger.append_episode(episode)

    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["model"] == "test-model"
    assert payload["events"][0]["kind"] == "episode_started"
    assert payload["events"][1]["kind"] == "reward"
    assert payload["events"][2]["kind"] == "episode_finished"
