import os
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider


class ProviderConfig(BaseModel):
    base_url: str
    api_key_env: str

    def get_api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            msg = f"Environment variable {self.api_key_env} not set"
            raise ValueError(msg)
        return key


class ModelConfig(BaseModel):
    model: str
    provider: str
    parallelism: int | None = None
    disable_tool_choice: bool = False


class BenchmarkConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    models: list[ModelConfig]
    years: list[int]
    parallelism: int = 1


def load_config(path: Path) -> BenchmarkConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return BenchmarkConfig.model_validate(data)


def create_model(
    model_id: str, provider: ProviderConfig, *, disable_tool_choice: bool = False
) -> OpenAIChatModel:
    openai_provider = OpenAIProvider(
        base_url=provider.base_url,
        api_key=provider.get_api_key(),
    )
    profile = None
    if disable_tool_choice:
        profile = OpenAIModelProfile(openai_supports_tool_choice_required=False)
    return OpenAIChatModel(model_id, provider=openai_provider, profile=profile)
