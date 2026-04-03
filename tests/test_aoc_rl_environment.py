import pytest

from aoc_agent.adapters.aoc.parser import SubmitStatus
from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.execute import ExecuteResult
from aoc_agent.tools.submit import SubmitResult
from aoc_rl.config import RewardConfig
from aoc_rl.environment import AocRLEnvironment


@pytest.mark.asyncio
async def test_environment_reuses_existing_tools_and_records_rewards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_description(ctx: object) -> str:
        assert ctx.deps.input_content == "1\n2\n3\n"
        return "problem text"

    async def fake_execute(ctx: object, code: str, **_: object) -> ExecuteResult:
        assert ctx.deps.input_content == "1\n2\n3\n"
        assert code == "print(42)"
        return ExecuteResult(output="42\n", error="")

    def fake_submit(ctx: object, part: int, answer: str) -> SubmitResult:
        assert part == 1
        assert answer == "42"
        ctx.deps.solve_status.part1_solved = True
        return SubmitResult(status=SubmitStatus.CORRECT)

    monkeypatch.setattr("aoc_rl.environment.call_problem_description", fake_description)
    monkeypatch.setattr("aoc_rl.environment.call_execute_python", fake_execute)
    monkeypatch.setattr("aoc_rl.environment.call_submit_answer", fake_submit)

    env = AocRLEnvironment(
        context=ToolContext(
            year=2022,
            day=1,
            input_content="1\n2\n3\n",
            solve_status=SolveStatus(),
            offline=True,
        ),
        reward_config=RewardConfig(
            part1_correct=2.0,
            tool_call_penalty=-0.25,
            free_tool_calls=1,
        ),
    )

    assert env.get_problem_description() == "problem text"
    execute_result = await env.execute_python("print(42)")
    submit_result = env.submit_answer(1, "42")
    trace = env.finish(termination_reason="completed")

    assert execute_result.output == "42\n"
    assert submit_result.status == SubmitStatus.CORRECT
    assert trace.total_reward == pytest.approx(1.5)
    assert trace.solved_part1 is True
    assert trace.solved_part2 is False
    assert trace.termination_reason == "completed"


@pytest.mark.asyncio
async def test_environment_timeout_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aoc_rl.environment.call_problem_description",
        lambda _ctx: "problem text",
    )

    async def fake_execute_timeout(ctx: object, code: str, **_: object) -> ExecuteResult:
        _ = (ctx, code)
        return ExecuteResult(output="", error="Execution timed out after 0.1s")

    monkeypatch.setattr("aoc_rl.environment.call_execute_python", fake_execute_timeout)

    env = AocRLEnvironment(
        context=ToolContext(
            year=2023,
            day=5,
            input_content="abc",
            solve_status=SolveStatus(),
            offline=True,
        ),
        reward_config=RewardConfig(
            tool_call_penalty=-0.1, python_timeout_penalty=-0.5, free_tool_calls=99
        ),
    )

    await env.execute_python("while True: pass")
    trace = env.finish(termination_reason="timeout")

    assert trace.total_reward == pytest.approx(-0.5)
    assert trace.termination_reason == "timeout"
