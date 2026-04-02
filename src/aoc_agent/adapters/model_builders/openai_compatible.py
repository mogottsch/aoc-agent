from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider


def build_model(
    model_name: str,
    base_url: str,
    api_key: str,
    *,
    disable_tool_choice: bool = False,
) -> Model:
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    profile = None
    if disable_tool_choice:
        profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
    return OpenAIChatModel(model_name, provider=provider, profile=profile)
