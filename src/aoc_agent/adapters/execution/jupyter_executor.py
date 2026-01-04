import asyncio
import contextlib
import json
import queue
from typing import Any, Protocol, runtime_checkable

from jupyter_client import AsyncKernelManager
from jupyter_client.asynchronous.client import AsyncKernelClient
from pydantic import BaseModel, TypeAdapter


class ExecuteResultPayload(BaseModel):
    data: dict[str, Any]


EXECUTE_RESULT_PAYLOAD_ADAPTER = TypeAdapter(ExecuteResultPayload)


class ExecutionTimeoutError(Exception):
    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(f"Execution timed out after {timeout_seconds}s")
        self.timeout_seconds = timeout_seconds


@runtime_checkable
class Executor(Protocol):
    async def execute(
        self,
        code: str,
        *,
        input_content: str,
        timeout_seconds: float = 30.0,
    ) -> tuple[str, str]: ...


class JupyterExecutor:
    def __init__(self, client: AsyncKernelClient, manager: AsyncKernelManager) -> None:
        self._client = client
        self._manager = manager

    async def execute(
        self,
        code: str,
        *,
        input_content: str,
        timeout_seconds: float = 30.0,
    ) -> tuple[str, str]:
        msg_id = self._client.execute(self._inject_input_content(input_content, code))
        try:
            async with asyncio.timeout(timeout_seconds):
                return await self._collect(msg_id)
        except TimeoutError:
            await self._manager.interrupt_kernel()
            with contextlib.suppress(TimeoutError):
                await self._wait_for_idle(msg_id)
            raise ExecutionTimeoutError(timeout_seconds) from None

    async def _collect(self, msg_id: str) -> tuple[str, str]:
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        while True:
            try:
                msg = await self._client.get_iopub_msg(timeout=1.0)
            except (TimeoutError, queue.Empty):
                continue
            if not self._is_parent(msg, msg_id):
                continue

            msg_type = msg["header"]["msg_type"]
            content = msg["content"]

            if self._is_idle(msg_type, content):
                break

            if msg_type == "stream":
                self._append_stream(content, stdout_parts, stderr_parts)
                continue

            if msg_type == "error":
                self._append_error(content, stderr_parts)
                continue

            if msg_type in {"execute_result", "display_data"}:
                self._append_display(content, stdout_parts)
                continue

        return "".join(stdout_parts), "".join(stderr_parts)

    async def _wait_for_idle(self, msg_id: str, *, max_seconds: float = 5.0) -> None:
        async with asyncio.timeout(max_seconds):
            while True:
                try:
                    msg = await self._client.get_iopub_msg(timeout=1.0)
                except (TimeoutError, queue.Empty):
                    continue
                if not self._is_parent(msg, msg_id):
                    continue
                msg_type = msg["header"]["msg_type"]
                content = msg["content"]
                if self._is_idle(msg_type, content):
                    return

    @staticmethod
    def _inject_input_content(input_content: str, code: str) -> str:
        return f"input_content = {json.dumps(input_content)}\n{code}"

    @staticmethod
    def _is_parent(msg: dict[str, Any], msg_id: str) -> bool:
        parent = msg.get("parent_header", {})
        return parent.get("msg_id") == msg_id

    @staticmethod
    def _append_stream(
        content: dict[str, Any],
        stdout_parts: list[str],
        stderr_parts: list[str],
    ) -> None:
        text = content.get("text", "")
        if content.get("name") == "stderr":
            stderr_parts.append(text)
        else:
            stdout_parts.append(text)

    @staticmethod
    def _append_error(content: dict[str, Any], stderr_parts: list[str]) -> None:
        traceback_lines = content.get("traceback", [])
        if traceback_lines:
            stderr_parts.append("\n".join(traceback_lines))
            return
        stderr_parts.append(f"{content.get('ename')}: {content.get('evalue')}")

    @staticmethod
    def _append_display(content: dict[str, Any], stdout_parts: list[str]) -> None:
        data = EXECUTE_RESULT_PAYLOAD_ADAPTER.validate_python(content).data
        text_plain = data.get("text/plain")
        if isinstance(text_plain, str):
            stdout_parts.append(f"{text_plain}\n")

    @staticmethod
    def _is_idle(msg_type: str, content: dict[str, Any]) -> bool:
        return msg_type == "status" and content.get("execution_state") == "idle"
