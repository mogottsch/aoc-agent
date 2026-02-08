import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationInfo, field_validator

from aoc_agent.core.constants import OutputMode


class ProviderConfig(BaseModel):
    base_url: str
    api_key_env: str | None = None

    def get_api_key(self) -> str:
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                msg = f"Environment variable {self.api_key_env} not set"
                raise ValueError(msg)
            return key
        if self.base_url.rstrip("/") == "https://api.githubcopilot.com":
            from aoc_agent.adapters.copilot.auth import get_copilot_token  # noqa: PLC0415

            return get_copilot_token()
        msg = "api_key_env is required for non-copilot providers"
        raise ValueError(msg)


class ModelConfig(BaseModel):
    model: str
    provider: str
    parallelism: int | None = None
    disable_tool_choice: bool = False
    openrouter_provider: str | None = None
    output_mode: OutputMode = OutputMode.TOOL

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


class BenchmarkConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    models: list[ModelConfig]
    years: list[int]
    per_model_parallelism: int = 1
    global_parallelism: int | None = None


def load_config(path: Path) -> BenchmarkConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return BenchmarkConfig.model_validate(data)
