from typing import Literal

from pydantic import BaseModel, Field


class ProviderTarget(BaseModel):
    base_url: str
    api_key: str = Field(repr=False)
    provider_name: str | None = None
    type: Literal["openai", "google"] = "openai"


class AvailableModel(BaseModel):
    id: str
    name: str | None = None
    owned_by: str | None = None
    context_length: int | None = None
