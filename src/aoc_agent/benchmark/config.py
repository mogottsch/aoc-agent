from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationInfo, field_validator, model_validator

from aoc_agent.adapters.auth import resolve_api_key_from_env
from aoc_agent.core.constants import OutputMode


class ProviderConfig(BaseModel):
    base_url: str
    api_key_env: str | None = None
    type: Literal["openai", "google"] = "openai"

    def get_api_key(self) -> str:
        return resolve_api_key_from_env(env_var=self.api_key_env, base_url=self.base_url)


class ModelConfig(BaseModel):
    model: str
    provider: str
    parallelism: int | None = None
    disable_tool_choice: bool = False
    openrouter_provider: str | None = None
    output_mode: OutputMode = OutputMode.TOOL
    use_responses_api: bool = False

    @field_validator("openrouter_provider")
    @classmethod
    def validate_openrouter_provider(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is not None and info.data.get("provider") != "openrouter":
            raise ValueError("openrouter_provider can only be set when provider is 'openrouter'")
        return v

    @field_validator("disable_tool_choice")
    @classmethod
    def validate_disable_tool_choice(cls, v: bool, info: ValidationInfo) -> bool:
        allowed = {"openrouter", "copilot"}
        if v and info.data.get("provider") not in allowed:
            msg = f"disable_tool_choice requires provider in {allowed}"
            raise ValueError(msg)
        return v

    @field_validator("use_responses_api")
    @classmethod
    def validate_use_responses_api(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("provider") != "copilot":
            raise ValueError("use_responses_api is only supported for the copilot provider")
        return v


class BenchmarkConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    models: list[ModelConfig]
    years: list[int]
    per_model_parallelism: int = 1
    global_parallelism: int | None = None

    @model_validator(mode="after")
    def validate_google_model_names(self) -> "BenchmarkConfig":
        for model in self.models:
            provider = self.providers.get(model.provider)
            if provider is None or provider.type != "google":
                continue
            if "/" not in model.model:
                continue
            msg = (
                f"Google provider '{model.provider}' requires bare Gemini API model IDs, "
                f"got '{model.model}'"
            )
            raise ValueError(msg)
        return self


def load_config(path: Path) -> BenchmarkConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return BenchmarkConfig.model_validate(data)
