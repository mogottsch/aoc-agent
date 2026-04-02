from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider


def build_model(model_name: str, api_key: str) -> Model:
    provider = GoogleProvider(api_key=api_key)
    return GoogleModel(model_name, provider=provider)
