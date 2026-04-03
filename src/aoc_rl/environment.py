from datetime import UTC, datetime

from pydantic import BaseModel

from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.execute import ExecuteResult
from aoc_agent.tools.submit import SubmitResult
from aoc_rl.config import RewardConfig
from aoc_rl.rewards import submission_reward, timeout_penalty, tool_penalty
from aoc_rl.run_context import as_run_context
from aoc_rl.tool_wrappers import (
    call_execute_python,
    call_problem_description,
    call_submit_answer,
)


class EpisodeResult(BaseModel):
    year: int
    day: int
    total_reward: float
    solved_part1: bool
    solved_part2: bool
    termination_reason: str
    finished_at: datetime


class AocRLEnvironment:
    def __init__(
        self,
        *,
        context: ToolContext,
        reward_config: RewardConfig,
    ) -> None:
        self._reward_config = reward_config
        self._tool_calls = 0
        self._total_reward = 0.0
        self._context = context
        self._run_context = as_run_context(self._context)
        self._year = context.year
        self._day = context.day

    def get_problem_description(self) -> str:
        self._record_tool_call("get_aoc_problem_description", {})
        return call_problem_description(self._run_context)

    async def execute_python(
        self,
        code: str,
        *,
        max_output_length: int = 2000,
        timeout_seconds: float = 30.0,
    ) -> ExecuteResult:
        self._record_tool_call(
            "execute_python",
            {
                "code": code,
                "max_output_length": max_output_length,
                "timeout_seconds": timeout_seconds,
            },
        )
        result = await call_execute_python(
            self._run_context,
            code,
            max_output_length=max_output_length,
            timeout_seconds=timeout_seconds,
        )
        if self._looks_like_timeout(result):
            self._add_reward(timeout_penalty(self._reward_config))
        return result

    def submit_answer(self, part: int, answer: int | str) -> SubmitResult:
        self._record_tool_call(
            "submit_answer",
            {"part": part, "answer": str(answer)},
        )
        result = call_submit_answer(self._run_context, part, answer)
        if result.status.value == "correct":
            reward = submission_reward(part, correct=True, config=self._reward_config)
            self._add_reward(reward)
        elif result.status.value in {"incorrect", "error"}:
            reward = submission_reward(part, correct=False, config=self._reward_config)
            self._add_reward(reward)
        return result

    def finish(self, *, termination_reason: str) -> EpisodeResult:
        return EpisodeResult(
            year=self._year,
            day=self._day,
            total_reward=self._total_reward,
            solved_part1=self._context.solve_status.part1_solved,
            solved_part2=self._context.solve_status.part2_solved,
            termination_reason=termination_reason,
            finished_at=datetime.now(tz=UTC),
        )

    @property
    def day(self) -> int:
        return self._day

    @property
    def solve_status(self) -> SolveStatus:
        return self._context.solve_status

    def _record_tool_call(
        self,
        _tool_name: str,
        _arguments: dict[str, str | int | float | bool | None],
    ) -> None:
        self._tool_calls += 1
        reward = tool_penalty(self._tool_calls, self._reward_config)
        if reward:
            self._add_reward(reward)

    def _add_reward(self, reward: float) -> None:
        self._total_reward += reward

    @staticmethod
    def _looks_like_timeout(result: ExecuteResult) -> bool:
        return "timed out" in result.error.lower()
