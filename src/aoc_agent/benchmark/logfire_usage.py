from __future__ import annotations

import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime

from logfire.experimental.query_client import LogfireQueryClient
from pydantic import BaseModel


class TraceUsage(BaseModel):
    trace_id: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int


_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


def _normalize_trace_ids(trace_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    for trace_id in trace_ids:
        if not _TRACE_ID_RE.fullmatch(trace_id):
            msg = f"Invalid trace_id: {trace_id}"
            raise ValueError(msg)
        normalized.append(trace_id.lower())
    return normalized


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _build_sql(trace_ids: list[str]) -> str:
    quoted = ", ".join(f"'{trace_id}'" for trace_id in trace_ids)
    return (
        "SELECT trace_id, "  # noqa: S608
        "SUM(COALESCE(CAST(attributes->>'gen_ai.usage.input_tokens' AS INT), 0)) AS input_tokens, "
        "SUM(COALESCE(CAST(attributes->>'gen_ai.usage.output_tokens' AS INT), 0)) "
        "AS output_tokens, "
        "SUM(COALESCE(CAST(attributes->>'gen_ai.usage.details.reasoning_tokens' AS INT), 0)) "
        "AS reasoning_tokens "
        "FROM records "
        f"WHERE trace_id IN ({quoted}) "
        "GROUP BY trace_id"
    )


def _query_with_retry(
    client: LogfireQueryClient, sql: str, min_timestamp: datetime, max_retries: int = 6
) -> list[dict]:
    # LogfireQueryClient raises AssertionError on non-200/400/422 responses (e.g. 429 rate limit).
    # Retry with exponential backoff: 5s, 10s, 20s, 40s, 80s, 160s.
    delay = 5.0
    for attempt in range(max_retries):
        try:
            return client.query_json_rows(sql, min_timestamp=min_timestamp)["rows"]
        except AssertionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def fetch_trace_usage(read_token: str, trace_ids: list[str]) -> list[TraceUsage]:
    if not trace_ids:
        return []
    trace_ids = _normalize_trace_ids(trace_ids)
    min_timestamp = datetime.min.replace(tzinfo=UTC)
    client = LogfireQueryClient(read_token=read_token)
    results: list[TraceUsage] = []
    for chunk in _chunked(trace_ids, 100):
        sql = _build_sql(chunk)
        rows = _query_with_retry(client, sql, min_timestamp)
        results.extend(TraceUsage.model_validate(row) for row in rows)
    return results
