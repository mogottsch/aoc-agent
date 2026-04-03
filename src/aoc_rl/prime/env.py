from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset
from verifiers.types import Messages, State

from aoc_agent.adapters.aoc.service import get_aoc_data_service
from aoc_agent.adapters.execution.jupyter import jupyter_context
from aoc_agent.core.constants import DAY_25
from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.context import ToolContext
from aoc_rl.config import RewardConfig
from aoc_rl.environment import AocRLEnvironment
from aoc_rl.prime.dataset import build_datasets


def get_aoc_problem_description(aoc_env: AocRLEnvironment) -> str:
    return aoc_env.get_problem_description()


async def execute_python(
    code: str,
    aoc_env: AocRLEnvironment,
    max_output_length: int = 2000,
    timeout_seconds: float = 30.0,
) -> str:
    result = await aoc_env.execute_python(
        code,
        max_output_length=max_output_length,
        timeout_seconds=timeout_seconds,
    )
    return result.model_dump_json()


def submit_answer(part: int, answer: str, aoc_env: AocRLEnvironment) -> str:
    result = aoc_env.submit_answer(part, answer)
    return result.model_dump_json()


class AocPrimeToolEnv(vf.StatefulToolEnv):
    def __init__(
        self,
        *,
        dataset: Dataset | list[dict[str, Any]],
        eval_dataset: Dataset | None = None,
    ) -> None:
        self.reward_config = RewardConfig()
        self._jupyter_contexts: dict[str, AbstractAsyncContextManager[ToolContext]] = {}
        super().__init__(
            tools=[],
            dataset=Dataset.from_list(dataset) if isinstance(dataset, list) else dataset,
            eval_dataset=eval_dataset,
            rubric=vf.Rubric(
                funcs=[self.total_reward, self.solved_part1_metric, self.solved_part2_metric]
            ),
            max_turns=8,
            env_id="aoc-rl-offline",
        )
        self.add_tool(get_aoc_problem_description, args_to_skip=["aoc_env"])
        self.add_tool(execute_python, args_to_skip=["aoc_env"])
        self.add_tool(submit_answer, args_to_skip=["aoc_env"])

    async def setup_state(self, state: State) -> State:
        info = state["info"]
        year = int(info["year"])
        day = int(info["day"])
        service = get_aoc_data_service(offline=True)
        data = service.get(year, day)
        base_context = ToolContext(
            year=year,
            day=day,
            input_content=data.input_content,
            solve_status=SolveStatus(),
            offline=True,
        )
        jupyter_cm = jupyter_context(base_context)
        tool_context = await jupyter_cm.__aenter__()
        self._jupyter_contexts[state["trajectory_id"]] = jupyter_cm
        aoc_env = AocRLEnvironment(
            context=tool_context,
            reward_config=self.reward_config,
        )
        state["aoc_env"] = aoc_env
        state["vf_reward"] = 0.0
        state["vf_metrics"] = {}
        return await super().setup_state(state)

    def update_tool_args(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        _messages: Messages,
        state: State,
        **_kwargs: object,
    ) -> dict[str, Any]:
        _ = tool_name
        tool_args["aoc_env"] = state["aoc_env"]
        return tool_args

    @vf.cleanup
    async def finalize_state(self, state: State) -> None:
        try:
            aoc_env = state["aoc_env"]
            result = aoc_env.finish(termination_reason=state.get("stop_condition") or "completed")
            state["vf_reward"] = result.total_reward
            state["vf_metrics"] = {
                "total_reward": result.total_reward,
                "solved_part1": 1.0 if result.solved_part1 else 0.0,
                "solved_part2": 1.0 if result.solved_part2 else 0.0,
            }
        finally:
            trajectory_id = state["trajectory_id"]
            jupyter_cm = self._jupyter_contexts.pop(trajectory_id, None)
            if jupyter_cm is not None:
                await jupyter_cm.__aexit__(None, None, None)

    @vf.stop(priority=100)
    async def stop_when_solved(self, state: State) -> bool:
        aoc_env = state.get("aoc_env")
        if aoc_env is None:
            return False
        solve_status = aoc_env.solve_status
        if aoc_env.day == DAY_25:
            return bool(solve_status.part1_solved)
        return bool(solve_status.part2_solved)

    async def total_reward(self, state: State, **_kwargs: object) -> float:
        return float(state.get("vf_reward", 0.0))

    async def solved_part1_metric(self, state: State, **_kwargs: object) -> float:
        return float(state.get("vf_metrics", {}).get("solved_part1", 0.0))

    async def solved_part2_metric(self, state: State, **_kwargs: object) -> float:
        return float(state.get("vf_metrics", {}).get("solved_part2", 0.0))


def create_environment(
    *,
    dataset: Dataset | list[dict[str, Any]],
    eval_dataset: Dataset | None = None,
) -> AocPrimeToolEnv:
    return AocPrimeToolEnv(
        dataset=dataset,
        eval_dataset=eval_dataset,
    )


def load_environment(
    *,
    cache_dir: Path | None = None,
    year: int | None = None,
) -> AocPrimeToolEnv:
    train_ds, eval_ds = build_datasets(
        cache_dir=cache_dir or Path("cache"),
        year=year,
    )
    return create_environment(
        dataset=train_ds,
        eval_dataset=eval_ds,
    )
