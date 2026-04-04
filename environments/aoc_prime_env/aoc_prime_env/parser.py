import re
from enum import Enum

from bs4 import BeautifulSoup


class SubmitStatus(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


def extract_answer_from_html(html: str, part: int) -> int | str | None:
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.find_all("article", class_="day-desc")
    article_index = part - 1
    if len(articles) <= article_index:
        return None
    answer_tag = articles[article_index].find_next_sibling("p")
    if not answer_tag or "Your puzzle answer was" not in str(answer_tag):
        return None
    code_tag = answer_tag.find("code")
    if not code_tag:
        return None
    text = code_tag.get_text()
    try:
        return int(text)
    except ValueError:
        return text


def extract_wait_time(text: str) -> float | None:
    minutes_short_match = re.search(r"(\d+)\s*m\s*(?:left|to|remaining)?", text.lower())
    if minutes_short_match:
        return float(minutes_short_match.group(1)) * 60
    seconds_short_match = re.search(r"(\d+)\s*s\s*(?:left|to|remaining)?", text.lower())
    if seconds_short_match:
        return float(seconds_short_match.group(1))
    minutes_full_match = re.search(r"(\d+)\s+minute", text.lower())
    if minutes_full_match:
        return float(minutes_full_match.group(1)) * 60
    seconds_full_match = re.search(r"(\d+)\s+second", text.lower())
    if seconds_full_match:
        return float(seconds_full_match.group(1))
    return None
