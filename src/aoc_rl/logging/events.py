from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class EventKind(StrEnum):
    EPISODE_STARTED = "episode_started"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PYTHON_EXECUTION = "python_execution"
    SUBMISSION = "submission"
    REWARD = "reward"
    EPISODE_FINISHED = "episode_finished"


class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: EventKind
    timestamp: datetime = Field(default_factory=_utc_now)
    step_index: int = Field(ge=0)


class EpisodeStartedEvent(BaseEvent):
    kind: Literal[EventKind.EPISODE_STARTED] = EventKind.EPISODE_STARTED
    model: str
    year: int
    day: int
    prompt_version: str


class AssistantMessageEvent(BaseEvent):
    kind: Literal[EventKind.ASSISTANT_MESSAGE] = EventKind.ASSISTANT_MESSAGE
    content: str


class ToolCallEvent(BaseEvent):
    kind: Literal[EventKind.TOOL_CALL] = EventKind.TOOL_CALL
    tool_name: str
    arguments: str


class ToolResultEvent(BaseEvent):
    kind: Literal[EventKind.TOOL_RESULT] = EventKind.TOOL_RESULT
    tool_name: str
    output: str
    error: str | None = None


class PythonExecutionEvent(BaseEvent):
    kind: Literal[EventKind.PYTHON_EXECUTION] = EventKind.PYTHON_EXECUTION
    code: str
    stdout: str
    stderr: str
    timeout_seconds: float


class SubmissionEvent(BaseEvent):
    kind: Literal[EventKind.SUBMISSION] = EventKind.SUBMISSION
    part: int = Field(ge=1, le=2)
    answer: str
    correct: bool | None = None
    message: str | None = None


class RewardEvent(BaseEvent):
    kind: Literal[EventKind.REWARD] = EventKind.REWARD
    reward: float
    source: str


class EpisodeFinishedEvent(BaseEvent):
    kind: Literal[EventKind.EPISODE_FINISHED] = EventKind.EPISODE_FINISHED
    solved_part1: bool
    solved_part2: bool
    total_reward: float
    termination_reason: str


TrajectoryEvent = (
    EpisodeStartedEvent
    | AssistantMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | PythonExecutionEvent
    | SubmissionEvent
    | RewardEvent
    | EpisodeFinishedEvent
)
