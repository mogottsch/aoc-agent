from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    aoc_session_token: str = Field(alias="AOC_SESSION_TOKEN")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
