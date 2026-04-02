import httpx

from aoc_agent.adapters.model_providers.common import extract_model_items, parse_openai_model_item
from aoc_agent.adapters.model_types import AvailableModel, ProviderTarget


def list_models(target: ProviderTarget) -> list[AvailableModel]:
    with httpx.Client(
        timeout=30.0, headers={"Authorization": f"Bearer {target.api_key}"}
    ) as client:
        response = client.get(models_url(target.base_url))
        response.raise_for_status()
        payload = response.json()
    models = [parse_openai_model_item(item) for item in extract_model_items(payload)]
    unique = {model.id: model for model in models}
    return sorted(unique.values(), key=lambda model: model.id)


def models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"
