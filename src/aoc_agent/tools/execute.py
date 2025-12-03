import io
from contextlib import redirect_stderr, redirect_stdout

from pydantic_ai import RunContext

from aoc_agent.tools.context import ToolContext


def execute_python(ctx: RunContext[ToolContext], code: str) -> str:
    """Execute Python code with access to the puzzle input.

    Args:
            code: Python code to execute. The input content is available as `input_content`.

    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    globals_dict = {"input_content": ctx.deps.input_content}

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, globals_dict)  # noqa: S102
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}\nStderr: {stderr_capture.getvalue()}"

    stdout = stdout_capture.getvalue()
    stderr = stderr_capture.getvalue()

    if stderr:
        return f"Stdout:\n{stdout}\nStderr:\n{stderr}"

    return stdout or "(no output)"
