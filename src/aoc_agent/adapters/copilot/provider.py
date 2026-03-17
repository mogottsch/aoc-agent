# The GitHub Copilot API claims OpenAI compatibility but has several undocumented quirks.
# _CopilotTransport works around these by rewriting requests and responses on the fly.
#
# Known quirks (discovered empirically):
#
# REQUEST - Claude models return 400 Bad Request if any tool has description="".
#   pydantic-ai sends description="" when no description is provided.
#   Fix: strip the description key when it is an empty string before sending.
#
# RESPONSE - Copilot omits the `object` field and per-choice `index` field from
#   /chat/completions responses. pydantic-ai expects both to be present.
#   Fix: inject them into the response body before pydantic-ai parses it.
#
# RESPONSE - Some Copilot models only support the /responses endpoint, not
#   /chat/completions. Those models must be configured with use_responses_api=true
#   in benchmark.yaml so pydantic-ai uses OpenAIResponsesModel instead.
#   Affected models: gpt-5.4, gpt-5.4-mini, gpt-5.3-codex.

import json

import httpx
from openai import AsyncOpenAI
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer, OpenAIModelProfile
from pydantic_ai.providers import Provider

COPILOT_BASE_URL = "https://api.githubcopilot.com"
COPILOT_HEADERS = {
    "Openai-Intent": "conversation-edits",
    "Editor-Version": "aoc-agent/0.1.0",
}


def _strip_empty_tool_descriptions(data: dict) -> dict:
    for tool in data.get("tools", []):
        fn = tool.get("function", {})
        if fn.get("description") == "":
            del fn["description"]
    return data


def _inject_missing_completion_fields(data: dict) -> dict:
    if data.get("object") is None:
        data["object"] = "chat.completion"
    for i, choice in enumerate(data.get("choices", [])):
        if choice.get("index") is None:
            choice["index"] = i
    return data


class _CopilotTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self._transport = transport

    def _rewrite_request(self, request: httpx.Request) -> httpx.Request:
        raw = request.content
        if not raw:
            return request
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return request
        patched = _strip_empty_tool_descriptions(data)
        new_body = json.dumps(patched).encode()
        headers = dict(request.headers)
        headers["content-length"] = str(len(new_body))
        return httpx.Request(
            method=request.method,
            url=request.url,
            headers=headers,
            content=new_body,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            request = self._rewrite_request(request)

        response = await self._transport.handle_async_request(request)
        if not request.url.path.endswith("/chat/completions"):
            return response
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return response
        raw = await response.aread()
        if not raw:
            return response
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=raw,
                request=request,
            )
        patched = _inject_missing_completion_fields(data)
        patched_bytes = json.dumps(patched).encode()
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=patched_bytes,
            request=request,
        )


class CopilotProvider(Provider[AsyncOpenAI]):
    def __init__(self, *, api_key: str) -> None:
        transport = _CopilotTransport(httpx.AsyncHTTPTransport())
        http_client = httpx.AsyncClient(headers=COPILOT_HEADERS, transport=transport)
        self._client = AsyncOpenAI(
            base_url=COPILOT_BASE_URL,
            api_key=api_key,
            http_client=http_client,
        )

    @property
    def name(self) -> str:
        return "copilot"

    @property
    def base_url(self) -> str:
        return COPILOT_BASE_URL

    @property
    def client(self) -> AsyncOpenAI:
        return self._client

    def model_profile(self, model_name: str) -> ModelProfile | None:  # noqa: ARG002
        return OpenAIModelProfile(json_schema_transformer=OpenAIJsonSchemaTransformer)
