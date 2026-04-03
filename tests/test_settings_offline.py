import pytest
from pydantic import ValidationError

from aoc_agent.core.settings import Settings


@pytest.mark.allow_missing_aoc_token
def test_settings_allows_missing_aoc_session_token_when_offline_eval_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AOC_SESSION_TOKEN", raising=False)
    settings = Settings.model_validate(
        {
            "MODEL": "test-model",
            "AOC_OFFLINE_ONLY": True,
            "AOC_SESSION_TOKEN": None,
        },
        by_alias=True,
    )

    assert settings.aoc_offline_only is True
    assert settings.aoc_session_token is None


@pytest.mark.allow_missing_aoc_token
def test_settings_requires_aoc_session_token_when_not_offline_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AOC_SESSION_TOKEN", raising=False)
    with pytest.raises(
        ValidationError,
        match="AOC_SESSION_TOKEN is required unless AOC_OFFLINE_ONLY=true",
    ):
        Settings.model_validate(
            {
                "MODEL": "test-model",
                "AOC_OFFLINE_ONLY": False,
                "AOC_SESSION_TOKEN": None,
            },
            by_alias=True,
        )
