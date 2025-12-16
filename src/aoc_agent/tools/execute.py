import io
from contextlib import redirect_stderr, redirect_stdout

from pydantic import BaseModel
from pydantic_ai import RunContext

from aoc_agent.tools.context import ToolContext


class ExecuteResult(BaseModel):
    output: str
    error: str


INPUT_CONTENT_VAR = "input_content"


def execute_python(ctx: RunContext[ToolContext], code: str) -> ExecuteResult:
    """
    Executes the provided Python code and captures its output and errors.

    To retrieve the output the code needs to print it to stdout. You will not
    be able to return values directly.
    The content of the input.txt file as downloaded from AoC is available in
    the variable `input_content`.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    globals_dict = {INPUT_CONTENT_VAR: ctx.deps.input_content}

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, globals_dict)  # noqa: S102
    except Exception as e:  # noqa: BLE001
        error_stderr = stderr_capture.getvalue()
        error_msg = f"Error: {e}"
        if error_stderr:
            error_msg = f"{error_msg}\n{error_stderr}"
        return ExecuteResult(output="", error=error_msg)

    stdout = stdout_capture.getvalue()
    stderr = stderr_capture.getvalue()

    return ExecuteResult(output=stdout, error=stderr)
