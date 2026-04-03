import json
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset
from verifiers.types import State, Tool, ToolMessage

from aoc_agent.adapters.aoc.parser import SubmitStatus
from aoc_rl.config import RewardConfig
from aoc_rl.environment import AocRLEnvironment


def make_problem_description_tool(adapter: AocRLEnvironment):
    def get_aoc_problem_description() -> str:
        return adapter.get_problem_description()

    return get_aoc_problem_description


def make_execute_python_tool(adapter: AocRLEnvironment):
    async def execute_python(
        code: str, max_output_length: int = 2000, timeout_seconds: float = 30.0
    ) -> str:
        result = await adapter.execute_python(
            code,
            max_output_length=max_output_length,
            timeout_seconds=timeout_seconds,
        )
        return result.model_dump_json()

    return execute_python


def make_submit_answer_tool(adapter: AocRLEnvironment):
    def submit_answer(part: int, answer: str) -> str:
        result = adapter.submit_answer(part, answer)
        return result.model_dump_json()

    return submit_answer


class AocPrimeToolEnv(vf.ToolEnv):
    def __init__(
        self,
        *,
        dataset: Dataset | list[dict[str, Any]],
        eval_dataset: Dataset | None = None,
        reward_config: RewardConfig | None = None,
        trajectory_dir: Path | None = None,
        max_turns: int = 8,
    ) -> None:
        self.reward_config = reward_config or RewardConfig()
        self.trajectory_dir = trajectory_dir
        self._adapters: dict[str, AocRLEnvironment] = {}
        super().__init__(
            tools=[],
            dataset=Dataset.from_list(dataset) if isinstance(dataset, list) else dataset,
            eval_dataset=eval_dataset,
            rubric=vf.Rubric(funcs=[self.total_reward, self.solved_part1_metric, self.solved_part2_metric]),
            max_turns=max_turns,
            env_id="aoc-rl-offline",
        )

    async def setup_state(self, state: State) -> State:
        info = state.get("info", {})
        year = int(info["year"])
        day = int(info["day"])
        prompt_version = str(info.get("prompt_version", "v1"))
        adapter = AocRLEnvironment(
            model=state["model"],
            year=year,
            day=day,
            prompt_version=prompt_version,
            reward_config=self.reward_config,
            trajectory_logger=None,
            offline=True,
        )
        trajectory_id = state["trajectory_id"]
        self._adapters[trajectory_id] = adapter
        state["adapter"] = adapter
        state["trajectory_id"] = trajectory_id
        problem_tool = make_problem_description_tool(adapter)
        execute_tool = make_execute_python_tool(adapter)
        submit_tool = make_submit_answer_tool(adapter)
        self.tools = [problem_tool, execute_tool, submit_tool]
        self.tool_defs = [self._tool_def(name) for name in [
            "get_aoc_problem_description",
            "execute_python",
            "submit_answer",
        ]]
        self.tool_map = {
            "get_aoc_problem_description": problem_tool,
            "execute_python": execute_tool,
            "submit_answer": submit_tool,
        }
        state["tool_defs"] = self.tool_defs
        state["vf_reward"] = 0.0
        state["vf_metrics"] = {}
        return state

    async def env_response(self, messages, state: State, **kwargs):
        trajectory_id = state["trajectory_id"]
        adapter = self._adapters[trajectory_id]
        last_msg = messages[-1]
        tool_messages: list[ToolMessage] = []
        for tool_call in last_msg.tool_calls or []:
            tool_name = tool_call.name
            tool_args = json.loads(tool_call.arguments)
            tool_func = self.tool_map[tool_name]
            result = tool_func(**tool_args)
            if hasattr(result, "__await__"):
                result = await result
            tool_messages.append(
                ToolMessage(role="tool", tool_call_id=tool_call.id, content=str(result))
            )
        return tool_messages

    @vf.cleanup
    async def finalize_state(self, state: State) -> None:
        trajectory_id = state["trajectory_id"]
        adapter = self._adapters.pop(trajectory_id)
        trace = adapter.finish(termination_reason=state.get("stop_condition") or "completed")
        finished = trace.finished_event
        state["vf_reward"] = trace.total_reward
        state["vf_metrics"] = {
            "total_reward": trace.total_reward,
            "solved_part1": 1.0 if (finished and finished.solved_part1) else 0.0,
            "solved_part2": 1.0 if (finished and finished.solved_part2) else 0.0,
        }

    async def total_reward(self, state: State, **kwargs) -> float:
        return float(state.get("vf_reward", 0.0))

    async def solved_part1_metric(self, state: State, **kwargs) -> float:
        return float(state.get("vf_metrics", {}).get("solved_part1", 0.0))

    async def solved_part2_metric(self, state: State, **kwargs) -> float:
        return float(state.get("vf_metrics", {}).get("solved_part2", 0.0))

    @staticmethod
    def _tool_def(name: str) -> Tool:
        if name == "get_aoc_problem_description":
            return Tool(name=name, description="Get current AoC problem description", parameters={"type": "object", "properties": {}, "required": []})
        if name == "execute_python":
            return Tool(
                name=name,
                description="Execute python against cached AoC input",
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "max_output_length": {"type": "integer"},
                        "timeout_seconds": {"type": "number"},
                    },
                    "required": ["code"],
                },
            )
        return Tool(
            name=name,
            description="Submit answer against offline cached AoC answers",
            parameters={
                "type": "object",
                "properties": {"part": {"type": "integer"}, "answer": {"type": "string"}},
                "required": ["part", "answer"],
            },
        )


def load_environment(
    dataset: Dataset | list[dict[str, Any]] | None = None,
    *,
    eval_dataset: Dataset | None = None,
    cache_dir: Path | None = None,
    results_path: Path | None = None,
    reward_config: RewardConfig | None = None,
    year: int | None = None,
) -> AocPrimeToolEnv:
    if dataset is None:
        from aoc_rl.prime.dataset import build_datasets

        train_ds, eval_ds = build_datasets(
            cache_dir=cache_dir or Path("cache"),
            results_path=results_path or Path("results/results.jsonl"),
            year=year,
        )
        dataset = train_ds
        eval_dataset = eval_dataset or eval_ds
    return AocPrimeToolEnv(
        dataset=dataset,
        eval_dataset=eval_dataset,
        reward_config=reward_config,
    )
