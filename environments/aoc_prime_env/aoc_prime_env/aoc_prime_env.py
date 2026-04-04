from datetime import UTC, datetime

import verifiers as vf
from datasets import Dataset
from pydantic import BaseModel
from verifiers.envs.python_env import PythonEnv, PythonWorkerState
from verifiers.envs.sandbox_env import SandboxState
from verifiers.types import Messages, State

from .constants import DAY_25, Part
from .dataset import (
    DEFAULT_DATASET_FILE,
    DEFAULT_DATASET_REPO,
    build_datasets,
    resolve_dataset_path,
)
from .models import SolveStatus
from .parser import SubmitStatus, extract_answer_from_html
from .rewards import RewardConfig, submission_reward, timeout_penalty, tool_penalty

MAX_TIMEOUT_SECONDS = 30.0


class ExecuteResult(BaseModel):
    output: str
    error: str


class SubmitResult(BaseModel):
    status: SubmitStatus
    message: str | None = None
    wait_seconds: float | None = None


class EpisodeResult(BaseModel):
    year: int
    day: int
    total_reward: float
    solved_part1: bool
    solved_part2: bool
    termination_reason: str
    finished_at: datetime


class AocPrimeEnv(PythonEnv):
    def __init__(
        self,
        *,
        dataset: Dataset,
        eval_dataset: Dataset | None = None,
        max_turns: int = 8,
        reward_config: RewardConfig | None = None,
    ) -> None:
        self.reward_config = reward_config or RewardConfig()
        super().__init__(
            dataset=dataset,
            eval_dataset=eval_dataset,
            env_id="aoc-prime-env",
            rubric=vf.Rubric(
                funcs=[self.total_reward, self.solved_part1_metric, self.solved_part2_metric]
            ),
            max_turns=max_turns,
            pip_install_packages="",
        )
        self.remove_tool(self.python)
        self.add_tool(self.get_aoc_problem_description, args_to_skip=["state"])
        self.add_tool(
            self.execute_python,
            args_to_skip=["sandbox_id", "sandbox_state", "python_state", "state"],
        )
        self.add_tool(self.submit_answer, args_to_skip=["state"])

    async def setup_state(self, state: State, **kwargs: object) -> State:
        state = await super().setup_state(state, **kwargs)
        info = state["info"]
        state["solve_status"] = SolveStatus()
        state["input_content"] = str(info["input_content"])
        state["tool_calls"] = 0
        state["vf_reward"] = 0.0
        state["vf_metrics"] = {}
        await self.python(
            code=f"input_content = {state['input_content']!r}",
            sandbox_id=state["sandbox_id"],
            sandbox_state=state["sandbox_state"],
            python_state=state["python_state"],
        )
        return state

    def update_tool_args(
        self,
        tool_name: str,
        tool_args: dict[str, object],
        messages: Messages,
        state: State,
        **kwargs: object,
    ) -> dict[str, object]:
        _ = messages, kwargs
        updated_args = dict(tool_args)
        if tool_name == "execute_python":
            updated_args["sandbox_id"] = state["sandbox_id"]
            updated_args["sandbox_state"] = state["sandbox_state"]
            updated_args["python_state"] = state["python_state"]
        updated_args["state"] = state
        return updated_args

    def get_aoc_problem_description(self, state: State) -> str:
        self.record_tool_call(state)
        solve_status = state["solve_status"]
        if solve_status.part1_solved:
            return str(state["info"]["part1_solved_html"])
        return str(state["info"]["unsolved_html"])

    async def execute_python(
        self,
        code: str,
        sandbox_id: str,
        sandbox_state: SandboxState,
        python_state: PythonWorkerState,
        state: State,
        max_output_length: int = 2000,
        timeout_seconds: float = 30.0,
    ) -> str:
        self.record_tool_call(state)
        if timeout_seconds > MAX_TIMEOUT_SECONDS:
            message = f"timeout_seconds must be <= {MAX_TIMEOUT_SECONDS}"
            raise ValueError(message)
        try:
            output = await self.python(
                code=f"{code}\n",
                sandbox_id=sandbox_id,
                sandbox_state=sandbox_state,
                python_state=python_state,
            )
        except vf.SandboxError:
            state["vf_reward"] += timeout_penalty(self.reward_config)
            return ExecuteResult(output="", error="Execution timed out").model_dump_json()
        if len(output) > max_output_length:
            half = max_output_length // 2
            output = (
                f"{output[:half]}\n\n"
                f"... [TRUNCATED {len(output) - max_output_length} CHARS] ...\n\n"
                f"{output[-half:]}"
            )
        return ExecuteResult(output=output, error="").model_dump_json()

    def submit_answer(self, part: int, answer: int | str, state: State) -> str:
        self.record_tool_call(state)
        if part not in (Part.ONE, Part.TWO):
            raise ValueError("part must be 1 or 2")
        if part == Part.TWO and int(state["info"]["day"]) == DAY_25:
            return SubmitResult(
                status=SubmitStatus.ERROR,
                message="Day 25 has no Part 2 submission",
            ).model_dump_json()
        solve_status = state["solve_status"]
        if part == Part.TWO and not solve_status.part1_solved:
            return SubmitResult(
                status=SubmitStatus.ERROR,
                message="Part 1 must be solved before submitting Part 2",
            ).model_dump_json()
        html = str(state["info"]["part1_solved_html" if part == Part.ONE else "part2_solved_html"])
        known = extract_answer_from_html(html, part)
        if known is None:
            return SubmitResult(
                status=SubmitStatus.ERROR,
                message="Dataset solved HTML does not contain an answer",
            ).model_dump_json()
        if str(known) == str(answer):
            if part == Part.ONE:
                solve_status.part1_solved = True
                solve_status.part1_incorrect_streak.reset()
            else:
                solve_status.part2_solved = True
                solve_status.part2_incorrect_streak.reset()
            state["vf_reward"] += submission_reward(part, correct=True, config=self.reward_config)
            return SubmitResult(status=SubmitStatus.CORRECT).model_dump_json()
        streak = (
            solve_status.part1_incorrect_streak
            if part == Part.ONE
            else solve_status.part2_incorrect_streak
        )
        streak.record_incorrect(answer)
        state["vf_reward"] += submission_reward(part, correct=False, config=self.reward_config)
        return SubmitResult(status=SubmitStatus.INCORRECT).model_dump_json()

    def record_tool_call(self, state: State) -> None:
        state["tool_calls"] += 1
        reward = tool_penalty(state["tool_calls"], self.reward_config)
        if reward:
            state["vf_reward"] += reward

    @vf.cleanup
    async def finalize_state(self, state: State) -> None:
        solve_status = state["solve_status"]
        result = EpisodeResult(
            year=int(state["info"]["year"]),
            day=int(state["info"]["day"]),
            total_reward=float(state.get("vf_reward", 0.0)),
            solved_part1=solve_status.part1_solved,
            solved_part2=solve_status.part2_solved,
            termination_reason=str(state.get("stop_condition") or "completed"),
            finished_at=datetime.now(tz=UTC),
        )
        state["vf_reward"] = result.total_reward
        state["vf_metrics"] = {
            "total_reward": result.total_reward,
            "solved_part1": 1.0 if result.solved_part1 else 0.0,
            "solved_part2": 1.0 if result.solved_part2 else 0.0,
        }

    @vf.stop(priority=100)
    async def stop_when_solved(self, state: State) -> bool:
        solve_status = state.get("solve_status")
        if solve_status is None:
            return False
        if int(state["info"]["day"]) == DAY_25:
            return bool(solve_status.part1_solved)
        return bool(solve_status.part2_solved)

    async def total_reward(self, state: State, **kwargs: object) -> float:
        _ = kwargs
        return float(state.get("vf_reward", 0.0))

    async def solved_part1_metric(self, state: State, **kwargs: object) -> float:
        _ = kwargs
        return float(state.get("vf_metrics", {}).get("solved_part1", 0.0))

    async def solved_part2_metric(self, state: State, **kwargs: object) -> float:
        _ = kwargs
        return float(state.get("vf_metrics", {}).get("solved_part2", 0.0))


def load_environment(
    dataset_path: str | None = None,
    dataset_repo: str = DEFAULT_DATASET_REPO,
    dataset_file: str = DEFAULT_DATASET_FILE,
    split: str = "train",
    max_examples: int | None = None,
    max_turns: int = 8,
) -> vf.Environment:
    resolved_dataset_path = resolve_dataset_path(dataset_path, dataset_repo, dataset_file)
    train_ds, eval_ds = build_datasets(resolved_dataset_path)
    if split == "train":
        dataset = train_ds
    elif split in {"eval", "validation", "test"}:
        if eval_ds is None:
            raise RuntimeError("No evaluation dataset available for requested split.")
        dataset = eval_ds
    else:
        raise ValueError("split must be one of: train, eval, validation, test")
    if max_examples is not None:
        dataset = dataset.select(range(min(max_examples, len(dataset))))
    return AocPrimeEnv(dataset=dataset, eval_dataset=eval_ds, max_turns=max_turns)
