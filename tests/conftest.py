import pytest


@pytest.fixture(autouse=True)
def set_dummy_aoc_session_token(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if request.node.get_closest_marker("allow_missing_aoc_token"):
        monkeypatch.delenv("AOC_SESSION_TOKEN", raising=False)
        return
    monkeypatch.setenv("AOC_SESSION_TOKEN", "dummy")
