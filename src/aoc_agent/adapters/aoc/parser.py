import re
from enum import Enum

from bs4 import BeautifulSoup
from pydantic import BaseModel


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


class SubmitResponse(BaseModel):
    status: SubmitStatus
    message: str | None = None
    wait_seconds: float | None = None


def _parse_incorrect(main_text: str) -> SubmitResponse | None:
    lower = main_text.lower()
    if "too high" in lower:
        return SubmitResponse(status=SubmitStatus.INCORRECT, message="Answer is too high")
    if "too low" in lower:
        return SubmitResponse(status=SubmitStatus.INCORRECT, message="Answer is too low")
    if "not the right answer" in lower:
        return SubmitResponse(status=SubmitStatus.INCORRECT)
    return None


def parse_submit_response(html: str) -> SubmitResponse:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")

    if not main:
        return SubmitResponse(status=SubmitStatus.ERROR, message="Could not parse response")

    main_text = main.get_text()

    if "That's the right answer" in main_text or "That's correct" in main_text:
        return SubmitResponse(status=SubmitStatus.CORRECT)

    if incorrect := _parse_incorrect(main_text):
        return incorrect

    if "too recently" in main_text.lower():
        wait_seconds = extract_wait_time(main_text)
        message = f"Rate limited: wait {wait_seconds:.0f}s" if wait_seconds else "Rate limited"
        return SubmitResponse(
            status=SubmitStatus.RATE_LIMITED, message=message, wait_seconds=wait_seconds
        )

    return SubmitResponse(status=SubmitStatus.ERROR, message="Unknown response from AOC")
