from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from bs4 import Tag

from aoc_agent.adapters.aoc.models import AOCData, ProblemHTML

_MIN_ARTICLES_FOR_PART2 = 2


def _has_part1_answer(first_article: "Tag") -> bool:
    first_answer = first_article.find_next_sibling("p")
    return first_answer is not None and "Your puzzle answer was" in str(first_answer)


def _is_part2_unlocked(articles: list["Tag"]) -> bool:
    return len(articles) >= _MIN_ARTICLES_FOR_PART2


def _has_full_completion(main: "Tag | None") -> bool:
    return bool(main and "day-success" in str(main))


def _build_part1_html(first_article: "Tag", articles: list["Tag"]) -> str | None:
    if not _has_part1_answer(first_article):
        return None

    first_answer = first_article.find_next_sibling("p")
    parts = [str(first_article), str(first_answer)]

    if _is_part2_unlocked(articles):
        parts.append(str(articles[1]))

    return "\n".join(parts)


def _fetch_problem_html(year: int, day: int, session_token: str) -> str:
    url = f"https://adventofcode.com/{year}/day/{day}"
    cookies = {"session": session_token}

    with httpx.Client(cookies=cookies, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _fetch_input_content(year: int, day: int, session_token: str) -> str:
    url = f"https://adventofcode.com/{year}/day/{day}/input"
    cookies = {"session": session_token}

    with httpx.Client(cookies=cookies, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _extract_problem_states(html: str) -> ProblemHTML:
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.find_all("article", class_="day-desc")
    main = soup.find("main")

    if not articles:
        raise ValueError("No problem articles found in HTML")

    unsolved_html = str(articles[0])
    first_article = articles[0]

    part1_solved_html = _build_part1_html(first_article, articles)
    if part1_solved_html is None:
        return ProblemHTML(
            unsolved_html=unsolved_html,
            part1_solved_html=None,
            part2_solved_html=None,
        )

    if not _has_full_completion(main):
        return ProblemHTML(
            unsolved_html=unsolved_html,
            part1_solved_html=part1_solved_html,
            part2_solved_html=None,
        )

    return ProblemHTML(
        unsolved_html=unsolved_html,
        part1_solved_html=part1_solved_html,
        part2_solved_html=str(main),
    )


def fetch_aoc_data(year: int, day: int, session_token: str) -> AOCData:
    problem_html_raw = _fetch_problem_html(year, day, session_token)
    problem_html = _extract_problem_states(problem_html_raw)
    input_content = _fetch_input_content(year, day, session_token)

    return AOCData(
        problem_html=problem_html,
        input_content=input_content,
    )
