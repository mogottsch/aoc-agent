import json
from pathlib import Path

import pytest

from aoc_agent.adapters.aoc.models import AOCData, ProblemHTML
from aoc_agent.adapters.aoc.parser import SubmitStatus
from aoc_agent.tools.execute import ExecuteResult
from aoc_agent.tools.submit import SubmitResult
from aoc_rl.config import RewardConfig
from aoc_rl.logging.events import EventKind
from aoc_rl.logging.trajectory import JsonlTrajectoryLogger


@pytest.mark.asyncio
async def test_environment_reuses_existing_tools_and_records_rewards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aoc_rl.environment import AocRLEnvironment

    class FakeService:
        def get(self, year: int, day: int) -> AOCData:
            assert (year, day) == (2022, 1)
            return AOCData(
                problem_html=ProblemHTML(unsolved_html="<html>problem</html>"),
                input_content="1\n2\n3\n",
            )

    def fake_description(ctx: object) -> str:
        assert getattr(ctx, "deps").input_content == "1\n2\n3\n"
        return "problem text"

    async def fake_execute(ctx: object, code: str, **_: object) -> ExecuteResult:
        assert getattr(ctx, "deps").input_content == "1\n2\n3\n"
        assert code == "print(42)"
        return ExecuteResult(output="42\n", error="")

    def fake_submit(ctx: object, part: int, answer: str) -> SubmitResult:
        assert part == 1
        assert answer == "42"
        getattr(ctx, "deps").solve_status.part1_solved = True
        return SubmitResult(status=SubmitStatus.CORRECT)

    monkeypatch.setattr("aoc_rl.environment.get_aoc_data_service", lambda offline=True: FakeService())
    monkeypatch.setattr("aoc_rl.environment.call_problem_description", fake_description)
    monkeypatch.setattr("aoc_rl.environment.call_execute_python", fake_execute)
    monkeypatch.setattr("aoc_rl.environment.call_submit_answer", fake_submit)

    env = AocRLEnvironment(
        model="test-model",
        year=2022,
        day=1,
        prompt_version="v1",
        reward_config=RewardConfig(part1_correct=2.0, tool_call_penalty=-0.25, free_tool_calls=1),
    )

    assert env.get_problem_description() == "problem text"
    execute_result = await env.execute_python("print(42)")
    submit_result = env.submit_answer(1, "42")
    trace = env.finish(termination_reason="completed")

    assert execute_result.output == "42\n"
    assert submit_result.status == SubmitStatus.CORRECT
    assert trace.total_reward == pytest.approx(1.5)
    assert trace.events[0].kind == EventKind.EPISODE_STARTED
    assert trace.events[-1].kind == EventKind.EPISODE_FINISHED
    assert trace.events[-1].solved_part1 is True
    reward_sources = [event.source for event in trace.events if event.kind == EventKind.REWARD]
    assert reward_sources == ["tool_call_penalty", "tool_call_penalty", "part1_correct"]


@pytest.mark.asyncio
async def test_environment_timeout_penalty_and_jsonl_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aoc_rl.environment import AocRLEnvironment

    class FakeService:
        def get(self, year: int, day: int) -> AOCData:
            assert (year, day) == (2023, 5)
            return AOCData(
                problem_html=ProblemHTML(unsolved_html="<html>problem</html>"),
                input_content="abc",
            )

    monkeypatch.setattr("aoc_rl.environment.get_aoc_data_service", lambda offline=True: FakeService())
    monkeypatch.setattr("aoc_rl.environment.call_problem_description", lambda ctx: "problem text")
    monkeypatch.setattr(
        "aoc_rl.environment.call_execute_python",
        lambda ctx, code, **_: ExecuteResult(output="", error="Execution timed out after 0.1s"),
    )

    env = AocRLEnvironment(
        model="timeout-model",
        year=2023,
        day=5,
        prompt_version="v1",
        reward_config=RewardConfig(tool_call_penalty=-0.1, python_timeout_penalty=-0.5, free_tool_calls=99),
        trajectory_logger=JsonlTrajectoryLogger(tmp_path),
    )

    await env.execute_python("while True: pass")
    trace = env.finish(termination_reason="timeout")

    assert trace.total_reward == pytest.approx(-0.5)
    path = tmp_path / "2023_05.jsonl"
    assert path.exists()
    payload = json.loads(path.read_text().splitlines()[0])
    assert payload["model"] == "timeout-model"
    assert payload["events"][-1]["termination_reason"] == "timeout"
