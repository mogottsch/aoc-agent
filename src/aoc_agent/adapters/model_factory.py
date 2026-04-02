from pydantic_ai.models import Model

from aoc_agent.adapters.model_builders import copilot, google, openai_compatible, openrouter
from aoc_agent.adapters.providers import (
    is_copilot_provider,
    is_google_provider,
    is_openrouter_provider,
)


def create_model(  # noqa: PLR0913
    model_name: str,
    base_url: str,
    api_key: str,
    *,
    disable_tool_choice: bool = False,
    openrouter_provider: str | None = None,
    provider_name: str | None = None,
    use_responses_api: bool = False,
    provider_type: str = "openai",
) -> Model:
    if is_google_provider(base_url, provider_type, provider_name):
        return google.build_model(model_name, api_key)

    if is_openrouter_provider(base_url, provider_name):
        return openrouter.build_model(
            model_name,
            api_key,
            disable_tool_choice=disable_tool_choice,
            openrouter_provider=openrouter_provider,
        )

    if is_copilot_provider(base_url, provider_name):
        return copilot.build_model(
            model_name,
            api_key,
            disable_tool_choice=disable_tool_choice,
            use_responses_api=use_responses_api,
        )

    return openai_compatible.build_model(
        model_name,
        base_url,
        api_key,
        disable_tool_choice=disable_tool_choice,
    )
