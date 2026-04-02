import os

from aoc_agent.adapters.copilot.auth import get_copilot_token
from aoc_agent.adapters.providers import is_copilot_provider


def resolve_api_key_from_value(
    api_key: str | None, *, base_url: str, provider_name: str | None = None
) -> str:
    if api_key:
        return api_key
    if is_copilot_provider(base_url, provider_name):
        return get_copilot_token()
    msg = "API_KEY is required for providers without built-in auth"
    raise ValueError(msg)


def resolve_api_key_from_env(
    *, env_var: str | None, base_url: str, provider_name: str | None = None
) -> str:
    if env_var:
        key = os.environ.get(env_var)
        if not key:
            msg = f"Environment variable {env_var} not set"
            raise ValueError(msg)
        return key
    return resolve_api_key_from_value(None, base_url=base_url, provider_name=provider_name)
