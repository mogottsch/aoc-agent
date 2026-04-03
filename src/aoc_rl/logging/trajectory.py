from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from aoc_rl.logging.events import TrajectoryEvent


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class EpisodeTrace(BaseModel):
    episode_id: str = Field(default_factory=lambda: str(uuid4()))
    model: str
    year: int
    day: int
    split: str | None = None
    prompt_version: str
    sampling: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = None
    events: list[TrajectoryEvent] = Field(default_factory=list)


class JsonlTrajectoryLogger:
    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def append_episode(self, episode: EpisodeTrace) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"{episode.year}_{episode.day:02d}.jsonl"
        with path.open("a") as handle:
            handle.write(episode.model_dump_json() + "\n")
        return path
