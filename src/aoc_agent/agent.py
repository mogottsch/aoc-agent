from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    aoc_day: int = Field(alias="AOC_DAY")
    aoc_year: int = Field(alias="AOC_YEAR")
    aoc_session_token: str = Field(alias="AOC_SESSION_TOKEN")


def main() -> None:
    settings = Settings()
    provider = OpenRouterProvider(api_key=settings.openrouter_api_key)
    model = OpenRouterModel("tngtech/deepseek-r1t2-chimera:free", provider=provider)
    agent = Agent(model)
    result = agent.run_sync("Hello")
    print(result.output)
