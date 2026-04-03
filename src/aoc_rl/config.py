from pathlib import Path

from pydantic import BaseModel, Field


class EpisodeLimits(BaseModel):
    max_steps: int = Field(default=40, ge=1)
    max_python_executions: int = Field(default=20, ge=1)
    max_submissions: int = Field(default=6, ge=1)
    max_duration_seconds: float = Field(default=600.0, gt=0)


class RewardConfig(BaseModel):
    part1_correct: float = 1.0
    part2_correct: float = 1.0
    tool_call_penalty: float = -0.02
    python_timeout_penalty: float = -0.05
    invalid_submission_penalty: float = -0.1
    free_tool_calls: int = 4


class RLConfig(BaseModel):
    manifest_path: Path = Path("configs/aoc_rl/manifest.jsonl")
    limits: EpisodeLimits = Field(default_factory=EpisodeLimits)
    reward: RewardConfig = Field(default_factory=RewardConfig)
