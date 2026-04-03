from pathlib import Path

import pytest
from datasets import Dataset
from verifiers.types import AssistantMessage, ClientConfig, ToolCall, UserMessage

from aoc_agent.adapters.aoc.models import AOCData, ProblemHTML
from aoc_agent.adapters.aoc.parser import SubmitStatus
from aoc_agent.tools.execute import ExecuteResult
from aoc_agent.tools.submit import SubmitResult
from aoc_rl.config import RewardConfig


def test_build_datasets_from_copied_cache_and_results(tmp_path: Path) -> None:
    from aoc_rl.prime.dataset import build_datasets

    cache_dir = tmp_path / "cache"
    year_dir_2022 = cache_dir / "2022"
    year_dir_2022.mkdir(parents=True)
    (year_dir_2022 / "day_1.unsolved.html").write_text("<html>problem</html>")
    (year_dir_2022 / "day_1.input.txt").write_text("1\n2\n")
    (year_dir_2022 / "day_1.part1_solved.html").write_text(
        "<article class='day-desc'></article><p>Your puzzle answer was <code>3</code></p>"
    )

    year_dir_2023 = cache_dir / "2023"
    year_dir_2023.mkdir(parents=True)
    (year_dir_2023 / "day_1.unsolved.html").write_text("<html>problem 2023</html>")
    (year_dir_2023 / "day_1.input.txt").write_text("3\n4\n")
    (year_dir_2023 / "day_1.part1_solved.html").write_text(
        "<article class='day-desc'></article><p>Your puzzle answer was <code>7</code></p>"
    )

    results_path = tmp_path / "results.jsonl"
    results_path.write_text(
        '{"model":"baseline","year":2022,"day":1,"part1_correct":true,"part2_correct":false}\n'
        '{"model":"baseline","year":2023,"day":1,"part1_correct":false,"part2_correct":false}\n'
    )

    train_ds, eval_ds = build_datasets(cache_dir=cache_dir, results_path=results_path, year=2022)

    assert isinstance(train_ds, Dataset)
    assert len(train_ds) == 1
    row = train_ds[0]
    assert row["year"] == 2022
    assert row["day"] == 1
    assert row["baseline_part1_correct"] is True
    assert row["answer"] == "3"
    assert eval_ds is not None


def test_build_datasets_without_year_filter_includes_multiple_years(tmp_path: Path) -> None:
    from aoc_rl.prime.dataset import build_datasets

    cache_dir = tmp_path / "cache"
    for year, answer in ((2022, "3"), (2023, "7")):
        year_dir = cache_dir / str(year)
        year_dir.mkdir(parents=True)
        (year_dir / "day_1.unsolved.html").write_text(f"<html>{year}</html>")
        (year_dir / "day_1.input.txt").write_text("1\n")
        (year_dir / "day_1.part1_solved.html").write_text(
            f"<article class='day-desc'></article><p>Your puzzle answer was <code>{answer}</code></p>"
        )

    results_path = tmp_path / "results.jsonl"
    results_path.write_text("")

    train_ds, _ = build_datasets(cache_dir=cache_dir, results_path=results_path)

    assert len(train_ds) == 2
    assert {train_ds[i]["year"] for i in range(len(train_ds))} == {2022, 2023}


@pytest.mark.asyncio
async def test_prime_tool_env_runs_offline_with_wrapped_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from aoc_rl.prime.env import load_environment

    class FakeService:
        def get(self, year: int, day: int) -> AOCData:
            assert (year, day) == (2022, 1)
            return AOCData(
                problem_html=ProblemHTML(unsolved_html="<html>problem</html>"),
                input_content="1\n2\n",
            )

    def fake_description(ctx: object) -> str:
        return "problem text"

    async def fake_execute(ctx: object, code: str, **_: object) -> ExecuteResult:
        assert code == "print(3)"
        return ExecuteResult(output="3\n", error="")

    def fake_submit(ctx: object, part: int, answer: str) -> SubmitResult:
        assert part == 1
        assert answer == "3"
        getattr(ctx, "deps").solve_status.part1_solved = True
        return SubmitResult(status=SubmitStatus.CORRECT)

    monkeypatch.setattr("aoc_rl.environment.get_aoc_data_service", lambda offline=True: FakeService())
    monkeypatch.setattr("aoc_rl.environment.call_problem_description", fake_description)
    monkeypatch.setattr("aoc_rl.environment.call_execute_python", fake_execute)
    monkeypatch.setattr("aoc_rl.environment.call_submit_answer", fake_submit)

    env = load_environment(
        dataset=[
            {
                "prompt": [{"role": "user", "content": "solve it"}],
                "answer": "3",
                "info": {"year": 2022, "day": 1, "prompt_version": "v1"},
            }
        ],
        reward_config=RewardConfig(part1_correct=2.0, tool_call_penalty=-0.25, free_tool_calls=99),
    )

    init_state = await env.init_state(
        env.dataset[0],
        client=ClientConfig(api_key_var="PRIME_API_KEY"),
        model="dummy-model",
    )
    state = await env.setup_state(init_state)

    state["trajectory"] = [
        {
            "prompt": [UserMessage(role="user", content="solve it")],
            "completion": [
                AssistantMessage(
                    role="assistant",
                    content="working",
                    tool_calls=[
                        ToolCall(id="1", name="get_aoc_problem_description", arguments="{}"),
                        ToolCall(id="2", name="execute_python", arguments='{"code":"print(3)"}'),
                        ToolCall(id="3", name="submit_answer", arguments='{"part":1,"answer":"3"}'),
                    ],
                )
            ],
            "response": None,
            "tokens": None,
            "reward": None,
            "advantage": None,
            "is_truncated": False,
            "trajectory_id": state["trajectory_id"],
            "extras": {},
        }
    ]

    tool_messages = await env.env_response(state["trajectory"][0]["completion"], state)
    assert len(tool_messages) == 3
    assert "problem text" in str(tool_messages[0].content)
    assert '"output":"3\\n"' in str(tool_messages[1].content)
    assert '"status":"correct"' in str(tool_messages[2].content)

    await env.finalize_state(state)
    assert state["vf_reward"] == pytest.approx(2.0)
    assert state["vf_metrics"]["total_reward"] == pytest.approx(2.0)
    assert state["vf_metrics"]["solved_part1"] == 1.0
