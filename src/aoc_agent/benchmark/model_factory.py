from pydantic_ai.models.openai import OpenAIChatModel

from aoc_agent.agent.factory import create_openai_model
from aoc_agent.benchmark.config import ProviderConfig


def create_benchmark_model(
    model_id: str,
    provider: ProviderConfig,
    *,
    disable_tool_choice: bool = False,
) -> OpenAIChatModel:
    return create_openai_model(
        model_name=model_id,
        base_url=provider.base_url,
        api_key=provider.get_api_key(),
        disable_tool_choice=disable_tool_choice,
    )
