from typing import Literal

from aoc_agent.adapters.copilot.provider import COPILOT_BASE_URL

GOOGLE_GLA_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENAI_BASE_URL = OPENROUTER_BASE_URL

ProviderType = Literal["openai", "google"]


def infer_provider_name(base_url: str) -> str | None:
    normalized = base_url.rstrip("/")
    if normalized == OPENROUTER_BASE_URL:
        return "openrouter"
    if normalized == COPILOT_BASE_URL:
        return "copilot"
    if normalized == GOOGLE_GLA_BASE_URL:
        return "google_aistudio"
    return None


def infer_provider_type(base_url: str, provider_name: str | None = None) -> ProviderType:
    if provider_name == "google_aistudio" or base_url.rstrip("/") == GOOGLE_GLA_BASE_URL:
        return "google"
    return "openai"


def is_copilot_provider(base_url: str, provider_name: str | None = None) -> bool:
    return provider_name == "copilot" or base_url.rstrip("/") == COPILOT_BASE_URL


def is_openrouter_provider(base_url: str, provider_name: str | None = None) -> bool:
    return provider_name == "openrouter" or base_url.rstrip("/") == OPENROUTER_BASE_URL


def is_google_provider(base_url: str, provider_type: str, provider_name: str | None = None) -> bool:
    return (
        provider_type == "google"
        or provider_name == "google_aistudio"
        or base_url.rstrip("/") == GOOGLE_GLA_BASE_URL
    )
