import json
import os
from pathlib import Path

from aoc_agent.adapters.auth import resolve_api_key_from_value
from aoc_agent.adapters.model_providers import copilot, google, openai_compatible
from aoc_agent.adapters.model_types import AvailableModel, ProviderTarget
from aoc_agent.adapters.providers import (
    DEFAULT_OPENAI_BASE_URL,
    infer_provider_name,
    infer_provider_type,
)
from aoc_agent.benchmark.config import load_config


def resolve_provider_target(provider_name: str | None, config_path: Path) -> ProviderTarget:
    if provider_name is None:
        return _resolve_provider_target_from_env()
    return _resolve_provider_target_from_config(provider_name, config_path)


def _resolve_provider_target_from_env() -> ProviderTarget:
    base_url = os.environ.get("API_BASE_URL", DEFAULT_OPENAI_BASE_URL)
    provider_name = infer_provider_name(base_url)
    provider_type = infer_provider_type(base_url, provider_name)
    api_key = resolve_api_key_from_value(
        os.environ.get("API_KEY"),
        base_url=base_url,
        provider_name=provider_name,
    )
    return ProviderTarget(
        base_url=base_url,
        api_key=api_key,
        provider_name=provider_name,
        type=provider_type,
    )


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
        type=provider.type,
    )


def list_available_models(target: ProviderTarget) -> list[AvailableModel]:
    if target.type == "google":
        return google.list_models(target)
    if copilot.is_target(target):
        return copilot.list_models(target)
    return openai_compatible.list_models(target)


def models_as_json(models: list[AvailableModel]) -> str:
    return json.dumps([model.model_dump(exclude_none=True) for model in models], indent=2)
