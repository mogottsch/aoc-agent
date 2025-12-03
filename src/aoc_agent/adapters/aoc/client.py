from functools import lru_cache

import httpx

from aoc_agent.core.settings import get_settings


class AOCClient:
    def __init__(self, session_token: str) -> None:
        self.session_token = session_token
        self._cookies = {"session": session_token}
        self._client = httpx.Client(cookies=self._cookies, timeout=30.0)

    def __del__(self) -> None:
        if hasattr(self, "_client"):
            self._client.close()

    def fetch_problem_html(self, year: int, day: int) -> str:
        url = f"https://adventofcode.com/{year}/day/{day}"
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def fetch_input(self, year: int, day: int) -> str:
        url = f"https://adventofcode.com/{year}/day/{day}/input"
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def submit_answer(self, year: int, day: int, part: int, answer: str) -> str:
        url = f"https://adventofcode.com/{year}/day/{day}/answer"
        data = {"level": str(part), "answer": answer}
        response = self._client.post(url, data=data)
        response.raise_for_status()
        return response.text


@lru_cache(maxsize=1)
def get_aoc_client() -> AOCClient:
    settings = get_settings()
    return AOCClient(settings.aoc_session_token)
