import pytest

from aoc_agent.adapters.aoc.parser import SubmitStatus
from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.submit import SubmitResult, submit_answer
from tests._helpers import as_run_context


def test_submit_same_incorrect_answer_three_times_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_check_known(*_args: object, **_kwargs: object) -> SubmitResult:
        return SubmitResult(status=SubmitStatus.INCORRECT)

    monkeypatch.setattr("aoc_agent.tools.submit.get_aoc_data_service", lambda: object())
    monkeypatch.setattr("aoc_agent.tools.submit._check_known", fake_check_known)

    deps = ToolContext(year=2024, day=1, input_content="", solve_status=SolveStatus())
    ctx = as_run_context(deps)

    submit_answer(ctx, 1, 123)
    submit_answer(ctx, 1, 123)
    with pytest.raises(RuntimeError, match="same incorrect answer submitted 3 times"):
        submit_answer(ctx, 1, 123)
