import pytest

from aoc_agent.core.models import SolveStatus
from aoc_agent.tools.context import ToolContext
from aoc_agent.tools.execute import _truncate, execute_python
from tests._helpers import as_run_context


def test_truncate_noop() -> None:
    s = "abc"
    assert _truncate(s, 2000) == s


def test_truncate_middle_snip() -> None:
    s = "A" * 3000
    out = _truncate(s, 2000)
    assert out.startswith("A" * 1000)
    assert out.endswith("A" * 1000)
    assert "[TRUNCATED 1000 CHARS]" in out


@pytest.mark.asyncio
async def test_execute_python_truncates_stdout_and_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeExecutor:
        def __init__(self, _client: object) -> None:
            pass

        async def execute(self, _code: str, *, input_content: str) -> tuple[str, str]:
            assert input_content == "inp"
            return "O" * 3000, "E" * 3000

    monkeypatch.setattr("aoc_agent.tools.execute.JupyterExecutor", FakeExecutor)
    deps = ToolContext(
        year=2024,
        day=1,
        input_content="inp",
        solve_status=SolveStatus(),
        kernel_client=object(),
    )
    ctx = as_run_context(deps)

    result = await execute_python(ctx, "print(1)", max_output_length=2000)
    assert result.output.startswith("O" * 1000)
    assert result.output.endswith("O" * 1000)
    assert "[TRUNCATED" in result.output
    assert result.error.startswith("E" * 1000)
    assert result.error.endswith("E" * 1000)
    assert "[TRUNCATED" in result.error
