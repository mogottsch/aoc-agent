from pydantic_ai.models import Model
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openrouter import OpenRouterProvider


def build_model(
    model_name: str,
    api_key: str,
    *,
    disable_tool_choice: bool = False,
    openrouter_provider: str | None = None,
) -> Model:
    provider = OpenRouterProvider(api_key=api_key)
    settings: OpenRouterModelSettings = {"openrouter_usage": {"include": True}}
    if openrouter_provider is not None:
        settings["openrouter_provider"] = {
            "only": [openrouter_provider],
            "allow_fallbacks": False,
        }
    profile = None
    if disable_tool_choice:
        profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
    return OpenRouterModel(model_name, provider=provider, profile=profile, settings=settings)
