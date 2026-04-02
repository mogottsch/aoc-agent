from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.profiles.openai import OpenAIModelProfile

from aoc_agent.adapters.copilot.provider import CopilotProvider


def build_model(
    model_name: str,
    api_key: str,
    *,
    disable_tool_choice: bool = False,
    use_responses_api: bool = False,
) -> Model:
    provider = CopilotProvider(api_key=api_key)
    profile = None
    if disable_tool_choice:
        profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
    if use_responses_api:
        return OpenAIResponsesModel(model_name, provider=provider, profile=profile)
    return OpenAIChatModel(model_name, provider=provider, profile=profile)
