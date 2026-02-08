from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from aoc_agent.core.constants import OutputMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="API_BASE_URL")
    api_key: str | None = Field(default=None, alias="API_KEY")
    aoc_session_token: str = Field(alias="AOC_SESSION_TOKEN")
    model: str = Field(default="google/gemini-3-pro-preview", alias="MODEL")
    disable_tool_choice: bool = Field(default=False, alias="DISABLE_TOOL_CHOICE")
    output_mode: OutputMode = Field(default=OutputMode.TOOL, alias="OUTPUT_MODE")
    logfire_read_token: str | None = Field(default=None, alias="LOGFIRE_READ_TOKEN")

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_base_url.rstrip("/") == "https://api.githubcopilot.com":
            from aoc_agent.adapters.copilot.auth import get_copilot_token  # noqa: PLC0415

            return get_copilot_token()
        msg = "API_KEY is required for non-copilot providers"
        raise ValueError(msg)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
