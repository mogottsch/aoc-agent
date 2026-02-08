from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from aoc_agent.core.constants import OutputMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="API_BASE_URL")
    api_key: str = Field(alias="API_KEY")
    aoc_session_token: str = Field(alias="AOC_SESSION_TOKEN")
    model: str = Field(default="google/gemini-3-pro-preview", alias="MODEL")
    disable_tool_choice: bool = Field(default=False, alias="DISABLE_TOOL_CHOICE")
    output_mode: OutputMode = Field(default=OutputMode.TOOL, alias="OUTPUT_MODE")
    logfire_read_token: str | None = Field(default=None, alias="LOGFIRE_READ_TOKEN")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
