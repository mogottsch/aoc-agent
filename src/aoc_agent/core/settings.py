from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aoc_agent.core.constants import OutputMode


class ExecutionSandbox(StrEnum):
    LOCAL = "local"
    CGROUP = "cgroup"


DEFAULT_EXECUTION_MEMORY_MB = 512
DEFAULT_EXECUTION_CPU_QUOTA_PERCENT = 100
DEFAULT_EXECUTION_TASKS_MAX = 64


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="API_BASE_URL")
    api_key: str | None = Field(default=None, alias="API_KEY")
    aoc_session_token: str = Field(alias="AOC_SESSION_TOKEN")
    model: str = Field(default="google/gemini-3-pro-preview", alias="MODEL")
    disable_tool_choice: bool = Field(default=False, alias="DISABLE_TOOL_CHOICE")
    output_mode: OutputMode = Field(default=OutputMode.TOOL, alias="OUTPUT_MODE")
    logfire_read_token: str | None = Field(default=None, alias="LOGFIRE_READ_TOKEN")
    execution_sandbox: ExecutionSandbox = Field(
        default=ExecutionSandbox.LOCAL,
        alias="EXECUTION_SANDBOX",
    )
    execution_memory_mb: int = Field(
        default=DEFAULT_EXECUTION_MEMORY_MB, alias="EXECUTION_MEMORY_MB"
    )
    execution_cpu_quota_percent: int = Field(
        default=DEFAULT_EXECUTION_CPU_QUOTA_PERCENT,
        alias="EXECUTION_CPU_QUOTA_PERCENT",
    )
    execution_tasks_max: int = Field(
        default=DEFAULT_EXECUTION_TASKS_MAX, alias="EXECUTION_TASKS_MAX"
    )

    @model_validator(mode="after")
    def validate_execution_sandbox(self) -> "Settings":
        if self.execution_sandbox != ExecutionSandbox.LOCAL:
            return self
        if self.execution_memory_mb != DEFAULT_EXECUTION_MEMORY_MB:
            msg = "EXECUTION_MEMORY_MB requires EXECUTION_SANDBOX=cgroup"
            raise ValueError(msg)
        if self.execution_cpu_quota_percent != DEFAULT_EXECUTION_CPU_QUOTA_PERCENT:
            msg = "EXECUTION_CPU_QUOTA_PERCENT requires EXECUTION_SANDBOX=cgroup"
            raise ValueError(msg)
        if self.execution_tasks_max != DEFAULT_EXECUTION_TASKS_MAX:
            msg = "EXECUTION_TASKS_MAX requires EXECUTION_SANDBOX=cgroup"
            raise ValueError(msg)
        return self

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
