from pathlib import Path

import pytest
from typer.testing import CliRunner

from aoc_agent.adapters.model_types import AvailableModel, ProviderTarget
from aoc_agent.adapters.models import (
    list_available_models,
    resolve_provider_target,
)
from aoc_agent.benchmark.config import load_config
from aoc_agent.cli import app


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FakeClient:
    def __init__(self, *, payload: object, capture: dict[str, object], **kwargs: object) -> None:
        self._payload = payload
        self._capture = capture
        self._capture["init_kwargs"] = kwargs

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str) -> FakeResponse:
        self._capture["url"] = url
        return FakeResponse(self._payload)


def test_resolve_provider_target_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("API_KEY", "test-key")

    target = resolve_provider_target(None, Path("benchmark.yaml"))

    assert target.base_url == "https://openrouter.ai/api/v1"
    assert target.api_key == "test-key"
    assert target.provider_name == "openrouter"


def test_resolve_google_provider_target_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("API_KEY", "google-key")

    target = resolve_provider_target(None, Path("benchmark.yaml"))

    assert target.base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert target.api_key == "google-key"
    assert target.provider_name == "google_aistudio"
    assert target.type == "google"


def test_resolve_provider_target_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "benchmark.yaml"
    config_path.write_text(
        "providers:\n"
        "  demo:\n"
        "    base_url: https://example.com/v1\n"
        "    api_key_env: DEMO_API_KEY\n"
        "models: []\n"
        "years: [2024]\n"
    )
    monkeypatch.setenv("DEMO_API_KEY", "demo-key")

    target = resolve_provider_target("demo", config_path)

    assert target.base_url == "https://example.com/v1"
    assert target.api_key == "demo-key"
    assert target.provider_name == "demo"


def test_resolve_google_provider_target_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "benchmark.yaml"
    config_path.write_text(
        "providers:\n"
        "  google_aistudio:\n"
        "    base_url: https://generativelanguage.googleapis.com/v1beta\n"
        "    api_key_env: GOOGLE_AISTUDIO_API_KEY\n"
        "    type: google\n"
        "models: []\n"
        "years: [2024]\n"
    )
    monkeypatch.setenv("GOOGLE_AISTUDIO_API_KEY", "google-key")

    target = resolve_provider_target("google_aistudio", config_path)

    assert target.base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert target.api_key == "google-key"
    assert target.provider_name == "google_aistudio"
    assert target.type == "google"


def test_provider_target_repr_redacts_api_key() -> None:
    target = ProviderTarget(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="google-key",
        provider_name="google_aistudio",
        type="google",
    )

    assert "google-key" not in repr(target)


def test_list_available_models_for_openrouter_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict[str, object] = {}
    payload = {
        "data": [
            {"id": "z-model", "name": "Z Model", "context_length": 128000},
            {"id": "a-model", "name": "A Model", "context_length": 64000},
        ]
    }

    def fake_client(**kwargs: object) -> FakeClient:
        return FakeClient(payload=payload, capture=capture, **kwargs)

    monkeypatch.setattr(
        "aoc_agent.adapters.model_providers.openai_compatible.httpx.Client", fake_client
    )

    models = list_available_models(
        ProviderTarget(
            base_url="https://openrouter.ai/api/v1", api_key="token", provider_name="openrouter"
        )
    )

    assert [model.id for model in models] == ["a-model", "z-model"]
    assert capture["url"] == "https://openrouter.ai/api/v1/models"
    assert capture["init_kwargs"] == {
        "timeout": 30.0,
        "headers": {"Authorization": "Bearer token"},
    }


def test_list_available_models_for_copilot_adds_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict[str, object] = {}
    payload = {"data": [{"id": "gpt-5.4"}]}

    def fake_client(**kwargs: object) -> FakeClient:
        return FakeClient(payload=payload, capture=capture, **kwargs)

    monkeypatch.setattr("aoc_agent.adapters.model_providers.copilot.httpx.Client", fake_client)

    models = list_available_models(
        ProviderTarget(
            base_url="https://api.githubcopilot.com", api_key="token", provider_name="copilot"
        )
    )

    assert [model.id for model in models] == ["gpt-5.4"]
    assert capture["url"] == "https://api.githubcopilot.com/models"
    assert capture["init_kwargs"] == {
        "timeout": 30.0,
        "headers": {
            "Authorization": "Bearer token",
            "Openai-Intent": "conversation-edits",
            "Editor-Version": "aoc-agent/0.1.0",
            "Content-Type": "application/json",
        },
    }


def test_list_available_models_for_google_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    capture: dict[str, object] = {}
    payload = {
        "models": [
            {
                "name": "models/gemini-2.5-pro",
                "displayName": "Gemini 2.5 Pro",
                "inputTokenLimit": 1048576,
            },
            {
                "name": "models/gemini-2.5-flash",
                "displayName": "Gemini 2.5 Flash",
                "inputTokenLimit": 1048576,
            },
        ]
    }

    def fake_client(**kwargs: object) -> FakeClient:
        return FakeClient(payload=payload, capture=capture, **kwargs)

    monkeypatch.setattr("aoc_agent.adapters.model_providers.google.httpx.Client", fake_client)

    models = list_available_models(
        ProviderTarget(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="token",
            provider_name="google_aistudio",
            type="google",
        )
    )

    assert [model.id for model in models] == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert capture["url"] == "https://generativelanguage.googleapis.com/v1beta/models"
    assert capture["init_kwargs"] == {
        "timeout": 30.0,
        "headers": {"x-goog-api-key": "token"},
    }


def test_google_provider_rejects_prefixed_model_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "benchmark.yaml"
    config_path.write_text(
        "providers:\n"
        "  google_aistudio:\n"
        "    base_url: https://generativelanguage.googleapis.com/v1beta\n"
        "    api_key_env: GOOGLE_AISTUDIO_API_KEY\n"
        "    type: google\n"
        "models:\n"
        "  - model: google/gemma-4-31b-it\n"
        "    provider: google_aistudio\n"
        "years: [2024]\n"
    )
    monkeypatch.setenv("GOOGLE_AISTUDIO_API_KEY", "google-key")

    with pytest.raises(ValueError, match="requires bare Gemini API model IDs"):
        load_config(config_path)


def test_models_command_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr(
        "aoc_agent.cli.resolve_provider_target",
        lambda provider, config: ProviderTarget(
            base_url="https://openrouter.ai/api/v1",
            api_key="token",
            provider_name=provider,
        ),
    )
    monkeypatch.setattr(
        "aoc_agent.cli.list_available_models",
        lambda target: [AvailableModel(id="a-model", name="A Model")],
    )

    result = runner.invoke(app, ["models", "--json"])

    assert result.exit_code == 0
    assert '"id": "a-model"' in result.stdout


def test_models_command_prints_plain_list(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr(
        "aoc_agent.cli.resolve_provider_target",
        lambda provider, config: ProviderTarget(
            base_url="https://api.githubcopilot.com",
            api_key="token",
            provider_name=provider,
        ),
    )
    monkeypatch.setattr(
        "aoc_agent.cli.list_available_models",
        lambda target: [AvailableModel(id="gpt-5.4"), AvailableModel(id="claude-sonnet-4.6")],
    )

    result = runner.invoke(app, ["models"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["gpt-5.4", "claude-sonnet-4.6"]
