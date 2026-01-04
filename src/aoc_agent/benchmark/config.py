import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationInfo, field_validator


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
    openrouter_provider: str | None = None

    @field_validator("openrouter_provider")
    @classmethod
    def validate_openrouter_provider(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is not None and info.data.get("provider") != "openrouter":
            raise ValueError("openrouter_provider can only be set when provider is 'openrouter'")
        return v

    @field_validator("disable_tool_choice")
    @classmethod
    def validate_disable_tool_choice(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("provider") != "openrouter":
            raise ValueError("disable_tool_choice can only be set when provider is 'openrouter'")
        return v


class BenchmarkConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    models: list[ModelConfig]
    years: list[int]
    parallelism: int = 1


def load_config(path: Path) -> BenchmarkConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return BenchmarkConfig.model_validate(data)
