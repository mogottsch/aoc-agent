import json
import os
from pathlib import Path

import httpx
from pydantic import BaseModel

from aoc_agent.adapters.copilot.auth import get_copilot_token
from aoc_agent.adapters.copilot.provider import COPILOT_BASE_URL, COPILOT_HEADERS
from aoc_agent.benchmark.config import load_config


class ProviderTarget(BaseModel):
    base_url: str
    api_key: str
    provider_name: str | None = None


class AvailableModel(BaseModel):
    id: str
    name: str | None = None
    owned_by: str | None = None
    context_length: int | None = None


def resolve_provider_target(provider_name: str | None, config_path: Path) -> ProviderTarget:
    if provider_name is None:
        return _resolve_provider_target_from_env()
    return _resolve_provider_target_from_config(provider_name, config_path)


def _resolve_provider_target_from_env() -> ProviderTarget:
    base_url = os.environ.get("API_BASE_URL", "https://openrouter.ai/api/v1")
    provider_name = _infer_provider_name(base_url)
    api_key = os.environ.get("API_KEY")
    if api_key is None and provider_name == "copilot":
        api_key = get_copilot_token()
    if api_key is None:
        msg = "API_KEY is required for non-copilot providers"
        raise ValueError(msg)
    return ProviderTarget(base_url=base_url, api_key=api_key, provider_name=provider_name)


def _resolve_provider_target_from_config(provider_name: str, config_path: Path) -> ProviderTarget:
    config = load_config(config_path)
    provider = config.providers.get(provider_name)
    if provider is None:
        msg = f"Unknown provider: {provider_name}"
        raise ValueError(msg)
    return ProviderTarget(
        base_url=provider.base_url,
        api_key=provider.get_api_key(),
        provider_name=provider_name,
    )


def _infer_provider_name(base_url: str) -> str | None:
    normalized = base_url.rstrip("/")
    if normalized == "https://openrouter.ai/api/v1":
        return "openrouter"
    if normalized == COPILOT_BASE_URL:
        return "copilot"
    return None


def list_available_models(target: ProviderTarget) -> list[AvailableModel]:
    headers = {"Authorization": f"Bearer {target.api_key}"}
    if _is_copilot_target(target):
        headers.update(COPILOT_HEADERS)
        headers["Content-Type"] = "application/json"
    with httpx.Client(timeout=30.0, headers=headers) as client:
        response = client.get(_models_url(target.base_url))
        response.raise_for_status()
        payload = response.json()
    models = [_parse_model_item(item) for item in _extract_model_items(payload)]
    unique = {model.id: model for model in models}
    return sorted(unique.values(), key=lambda model: model.id)


def models_as_json(models: list[AvailableModel]) -> str:
    return json.dumps([model.model_dump(exclude_none=True) for model in models], indent=2)


def _is_copilot_target(target: ProviderTarget) -> bool:
    return target.provider_name == "copilot" or target.base_url.rstrip("/") == COPILOT_BASE_URL


def _models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def _extract_model_items(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        msg = "Provider returned an unsupported models payload"
        raise TypeError(msg)
    data = payload.get("data")
    if isinstance(data, list):
        return data
    items = payload.get("models")
    if isinstance(items, list):
        return items
    msg = "Provider returned a models payload without a model list"
    raise ValueError(msg)


def _parse_model_item(item: object) -> AvailableModel:
    if not isinstance(item, dict):
        msg = "Provider returned a malformed model entry"
        raise TypeError(msg)
    model_id = _read_string(item, "id") or _read_string(item, "name")
    if model_id is None:
        msg = "Provider returned a model entry without an id"
        raise ValueError(msg)
    return AvailableModel(
        id=model_id,
        name=_read_string(item, "name"),
        owned_by=_read_string(item, "owned_by"),
        context_length=_read_context_length(item),
    )


def _read_string(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return None


def _read_context_length(data: dict[str, object]) -> int | None:
    direct = _coerce_int(data.get("context_length"))
    if direct is not None:
        return direct
    top_provider = data.get("top_provider")
    if not isinstance(top_provider, dict):
        return None
    return _coerce_int(top_provider.get("context_length"))


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
