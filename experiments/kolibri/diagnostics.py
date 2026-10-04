"""Private, local-only failure evidence. Never serialize environment or frame locals."""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    known = set(secrets)
    known.update(
        value
        for name, value in os.environ.items()
        if re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|COOKIE", name, re.IGNORECASE) and value
    )
    for value in sorted(known, key=len, reverse=True):
        if value:
            text = text.replace(value, "[REDACTED]")
            # Provider bodies may already be JSON strings nested inside metadata JSON.
            encoded = value
            for _ in range(2):
                encoded = json.dumps(encoded)[1:-1]
                text = text.replace(encoded, "[REDACTED]")
    return re.sub(r"(?i)\bBearer\s+[^\s\"'<>\\,;]+", "Bearer [REDACTED]", text)


def private_write(path: Path, text: str) -> None:
    # Exclusive temporary file + atomic replacement; refuse preexisting symlink targets.
    if path.is_symlink():
        raise ValueError("unsafe diagnostic path")
    temporary = path.with_name(path.name + ".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class RedactingStream:
    """Emit safe prefixes promptly; hold only possible cross-read credentials."""

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self.secrets = tuple(
            set(secrets)
            | {
                value
                for name, value in os.environ.items()
                if re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|COOKIE", name, re.IGNORECASE) and value
            }
        )
        variants = set(self.secrets)
        for value in self.secrets:
            encoded = value
            for _ in range(2):
                encoded = json.dumps(encoded)[1:-1]
                variants.add(encoded)
        self.secrets = tuple(variants)
        self.pending = ""
        self.hold = max([16, *(len(s) for s in self.secrets)])

    def feed(self, text: str, *, final: bool = False) -> str:
        data = self.pending + text
        cut = len(data) if final else max(0, len(data) - self.hold)
        if not final:
            patterns = [re.escape(s) for s in self.secrets if s]
            patterns.append(r"(?i:\bBearer\s+[^\s\"'<>\\,;]*)")
            for match in re.finditer("|".join(patterns), data):
                if match.start() < cut < match.end():
                    cut = match.start()
        self.pending = data[cut:]
        return redact(data[:cut], self.secrets)


def exception_metadata(error: BaseException, seen: set[int] | None = None) -> dict:
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"type": type(error).__name__, "cycle": True}
    seen.add(id(error))
    data: dict = {
        "type": type(error).__name__,
        "module": type(error).__module__,
        "message": redact(str(error)),
    }
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if isinstance(status, int):
        data["status_code"] = status
    body = getattr(error, "body", None)
    if body is None and response is not None:
        try:
            body = response.text
        except Exception:  # noqa: BLE001 - streamed/unread response has no safe body
            body = "[response body unavailable]"
    if body is not None:
        data["body"] = redact(body if isinstance(body, str) else json.dumps(body, default=str))
    if error.__cause__ is not None:
        data["cause"] = exception_metadata(error.__cause__, seen)
    elif error.__context__ is not None and not error.__suppress_context__:
        data["context"] = exception_metadata(error.__context__, seen)
    return data


def save_failure(  # noqa: PLR0913 - explicit context and redaction inputs
    directory: Path,
    error: BaseException,
    *,
    year: int | None = None,
    day: int | None = None,
    prefix: str = "failure",
    secrets: tuple[str, ...] = (),
) -> None:
    text = "".join(
        traceback.TracebackException.from_exception(
            error, capture_locals=False, max_group_width=sys.maxsize, max_group_depth=sys.maxsize
        ).format()
    )
    private_write(directory / (prefix + "-traceback.txt"), redact(text, secrets))
    private_write(
        directory / (prefix + ".json"),
        redact(
            json.dumps(
                {
                    "year": year,
                    "day": day,
                    "exception": exception_metadata(error),
                },
                indent=2,
            )
            + "\n",
            secrets,
        ),
    )
