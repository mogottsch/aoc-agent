from functools import lru_cache

from aoc_agent.adapters.aoc.fetcher import fetch_aoc_data
from aoc_agent.adapters.aoc.models import AOCData
from aoc_agent.adapters.storage.data_store import AOCDataStore, get_data_store
from aoc_agent.core.models import Answers


class AOCDataService:
    def __init__(self, store: AOCDataStore) -> None:
        self._store = store

    def _is_complete(self, data: AOCData | None) -> bool:
        return data is not None and data.problem_html.part2_solved_html is not None

    def get(self, year: int, day: int) -> AOCData:
        cached = self._store.get(year, day)
        if self._is_complete(cached):
            return cached
        fresh = fetch_aoc_data(year, day)
        self._store.merge(year, day, fresh)
        return self._store.get(year, day) or fresh

    def get_answers(self, year: int, day: int) -> Answers:
        self.get(year, day)
        return self._store.get_answers(year, day)


@lru_cache(maxsize=1)
def get_aoc_data_service() -> AOCDataService:
    return AOCDataService(get_data_store())
