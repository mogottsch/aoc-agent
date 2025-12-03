from pathlib import Path

from aoc_agent.adapters.aoc.models import AOCData


class FileCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_paths(self, year: int, day: int) -> tuple[Path, Path]:
        year_dir = self.cache_dir / str(year)
        year_dir.mkdir(exist_ok=True)
        html_path = year_dir / f"day_{day}.html"
        input_path = year_dir / f"day_{day}.input.txt"
        return html_path, input_path

    def get(self, year: int, day: int) -> AOCData | None:
        html_path, input_path = self._get_paths(year, day)
        if not html_path.exists() or not input_path.exists():
            return None
        problem_html = html_path.read_text()
        input_content = input_path.read_text()
        return AOCData(problem_html=problem_html, input_content=input_content)

    def store(self, year: int, day: int, data: AOCData) -> None:
        html_path, input_path = self._get_paths(year, day)
        html_path.write_text(data.problem_html)
        input_path.write_text(data.input_content)

    def exists(self, year: int, day: int) -> bool:
        html_path, input_path = self._get_paths(year, day)
        return html_path.exists() and input_path.exists()
