from datetime import UTC, datetime
from inspect import isawaitable

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.execute import ExecuteResult
from aoc_agent.tools.submit import SubmitResult
from aoc_agent.tools.context import ToolContext
from aoc_rl.config import RewardConfig
from aoc_rl.logging.events import (
    AssistantMessageEvent,
    EpisodeFinishedEvent,
    EpisodeStartedEvent,
    PythonExecutionEvent,
    RewardEvent,
    SubmissionEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from aoc_rl.logging.trajectory import EpisodeTrace, JsonlTrajectoryLogger
from aoc_rl.rewards import submission_reward, timeout_penalty, tool_penalty
from aoc_rl.run_context import as_run_context
from aoc_rl.tool_wrappers import call_execute_python, call_problem_description, call_submit_answer


class AocRLEnvironment:
    def __init__(
        self,
        *,
        model: str,
        year: int,
        day: int,
        prompt_version: str,
        reward_config: RewardConfig,
        trajectory_logger: JsonlTrajectoryLogger | None = None,
        offline: bool = True,
    ) -> None:
        service = get_aoc_data_service(offline=offline)
        data = service.get(year, day)
        self._reward_config = reward_config
        self._trajectory_logger = trajectory_logger
        self._tool_calls = 0
        self._step_index = 0
        self._context = ToolContext(
            year=year,
            day=day,
            input_content=data.input_content,
            solve_status=SolveStatus(),
            offline=offline,
        )
        self._run_context = as_run_context(self._context)
        self._trace = EpisodeTrace(
            model=model,
            year=year,
            day=day,
            prompt_version=prompt_version,
            events=[
                EpisodeStartedEvent(
                    step_index=0,
                    model=model,
                    year=year,
                    day=day,
                    prompt_version=prompt_version,
                )
            ],
        )

    def get_problem_description(self) -> str:
        self._record_tool_call("get_aoc_problem_description", "{}")
        description = call_problem_description(self._run_context)
        self._record_tool_result("get_aoc_problem_description", description)
        return description

    async def execute_python(
        self,
        code: str,
        *,
        max_output_length: int = 2000,
        timeout_seconds: float = 30.0,
    ) -> ExecuteResult:
        self._record_tool_call(
            "execute_python",
            f'{{"code": {code!r}, "max_output_length": {max_output_length}, "timeout_seconds": {timeout_seconds}}}',
        )
        execution = call_execute_python(
            self._run_context,
            code,
            max_output_length=max_output_length,
            timeout_seconds=timeout_seconds,
        )
        result = await execution if isawaitable(execution) else execution
        self._record_python_execution(code, result, timeout_seconds)
        self._record_tool_result("execute_python", result.output, error=result.error or None)
        if self._looks_like_timeout(result):
            self._add_reward(timeout_penalty(self._reward_config), "python_timeout_penalty")
        return result

    def submit_answer(self, part: int, answer: int | str) -> SubmitResult:
        self._record_tool_call("submit_answer", f'{{"part": {part}, "answer": {str(answer)!r}}}')
        result = call_submit_answer(self._run_context, part, answer)
        self._record_submission(part, str(answer), result)
        self._record_tool_result("submit_answer", result.model_dump_json())
        if result.status.value == "correct":
            reward = submission_reward(part, correct=True, config=self._reward_config)
            self._add_reward(reward, "part1_correct" if part == 1 else "part2_correct")
        elif result.status.value in {"incorrect", "error"}:
            reward = submission_reward(part, correct=False, config=self._reward_config)
            self._add_reward(reward, "invalid_submission_penalty")
        return result

    def record_assistant_message(self, content: str) -> None:
        self._step_index += 1
        self._trace.events.append(AssistantMessageEvent(step_index=self._step_index, content=content))

    def finish(self, *, termination_reason: str) -> EpisodeTrace:
        finished_at = datetime.now(tz=UTC)
        self._trace.finished_at = finished_at
        finished_event = EpisodeFinishedEvent(
            step_index=self._step_index + 1,
            solved_part1=self._context.solve_status.part1_solved,
            solved_part2=self._context.solve_status.part2_solved,
            total_reward=self._trace.total_reward,
            termination_reason=termination_reason,
        )
        self._trace.events.append(finished_event)
        if self._trajectory_logger is not None:
            self._trajectory_logger.append_episode(self._trace)
        return self._trace

    def _record_tool_call(self, tool_name: str, arguments: str) -> None:
        self._step_index += 1
        self._tool_calls += 1
        self._trace.events.append(
            ToolCallEvent(step_index=self._step_index, tool_name=tool_name, arguments=arguments)
        )
        reward = tool_penalty(self._tool_calls, self._reward_config)
        if reward:
            self._add_reward(reward, "tool_call_penalty")

    def _record_tool_result(self, tool_name: str, output: str, *, error: str | None = None) -> None:
        self._step_index += 1
        self._trace.events.append(
            ToolResultEvent(step_index=self._step_index, tool_name=tool_name, output=output, error=error)
        )

    def _record_python_execution(
        self, code: str, result: ExecuteResult, timeout_seconds: float
    ) -> None:
        self._step_index += 1
        self._trace.events.append(
            PythonExecutionEvent(
                step_index=self._step_index,
                code=code,
                stdout=result.output,
                stderr=result.error,
                timeout_seconds=timeout_seconds,
            )
        )

    def _record_submission(self, part: int, answer: str, result: SubmitResult) -> None:
        self._step_index += 1
        self._trace.events.append(
            SubmissionEvent(
                step_index=self._step_index,
                part=part,
                answer=answer,
                correct=result.status.value == "correct",
                message=result.message,
            )
        )

    def _add_reward(self, reward: float, source: str) -> None:
        self._step_index += 1
        self._trace.events.append(RewardEvent(step_index=self._step_index, reward=reward, source=source))

    @staticmethod
    def _looks_like_timeout(result: ExecuteResult) -> bool:
        return "timed out" in result.error.lower()
