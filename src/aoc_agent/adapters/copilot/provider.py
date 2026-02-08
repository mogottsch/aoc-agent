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


def _patch_completion(data: dict) -> dict:
    if data.get("object") is None:
        data["object"] = "chat.completion"
    for i, choice in enumerate(data.get("choices", [])):
        if choice.get("index") is None:
            choice["index"] = i
    return data


class _CopilotTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self._transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._transport.handle_async_request(request)
        if not request.url.path.endswith("/chat/completions"):
            return response
        raw = await response.aread()
        data = json.loads(raw)
        patched = _patch_completion(data)
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
