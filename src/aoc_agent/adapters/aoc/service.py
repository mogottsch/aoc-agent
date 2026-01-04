from functools import lru_cache
from typing import cast

from aoc_agent.adapters.aoc.fetcher import fetch_aoc_data
from aoc_agent.adapters.aoc.models import AOCData
from aoc_agent.adapters.storage.data_store import AOCDataStore, get_data_store
from aoc_agent.core.constants import Part
from aoc_agent.core.models import Answers


class AOCDataService:
    def __init__(self, store: AOCDataStore, offline: bool = False) -> None:
        self._store = store
        self._offline = offline

    def _is_complete(self, data: AOCData | None) -> bool:
        return data is not None and data.problem_html.part2_solved_html is not None

    def get(self, year: int, day: int) -> AOCData:
        cached = self._store.get(year, day)
        if self._is_complete(cached):
            return cast(AOCData, cached)

        if self._offline:
            if cached is None:
                msg = f"No cached data found for {year} day {day} and offline mode is enabled"
                raise RuntimeError(msg)
            return cached

        fresh = fetch_aoc_data(year, day)
        self._store.merge(year, day, fresh)
        return self._store.get(year, day) or fresh

    def get_answers(self, year: int, day: int) -> Answers:
        self.get(year, day)
        return self._store.get_answers(year, day)

    def is_part_solved(self, year: int, day: int, part: int) -> bool:
        data = self._store.get(year, day)
        if data is None:
            return False

        if part == Part.ONE:
            return data.problem_html.part1_solved_html is not None

        return data.problem_html.part2_solved_html is not None


@lru_cache(maxsize=2)
def get_aoc_data_service(offline: bool = False) -> AOCDataService:
    return AOCDataService(get_data_store(), offline=offline)
