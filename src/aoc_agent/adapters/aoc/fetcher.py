from bs4 import BeautifulSoup, Tag

from aoc_agent.adapters.aoc.client import get_aoc_client
from aoc_agent.adapters.aoc.models import AOCData, ProblemHTML

_MIN_ARTICLES_FOR_PART2 = 2


def _has_part1_answer(first_article: Tag) -> bool:
    first_answer = first_article.find_next_sibling("p")
    return first_answer is not None and "Your puzzle answer was" in str(first_answer)


def _is_part2_unlocked(articles: list["Tag"]) -> bool:
    return len(articles) >= _MIN_ARTICLES_FOR_PART2


def _has_full_completion(main: Tag | None) -> bool:
    return bool(main and "day-success" in str(main))


def _build_part1_html(first_article: Tag, articles: list[Tag]) -> str | None:
    if not _has_part1_answer(first_article):
        return None

    first_answer = first_article.find_next_sibling("p")
    parts = [str(first_article), str(first_answer)]

    if _is_part2_unlocked(articles):
        parts.append(str(articles[1]))

    return "\n".join(parts)


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


def fetch_aoc_data(year: int, day: int) -> AOCData:
    client = get_aoc_client()
    problem_html_raw = client.fetch_problem_html(year, day)
    problem_html = _extract_problem_states(problem_html_raw)
    input_content = client.fetch_input(year, day)

    return AOCData(
        problem_html=problem_html,
        input_content=input_content,
    )
