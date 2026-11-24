"""Small, explicit classifiers for requests that need current information."""

import re
from datetime import datetime


def current_datetime_request(text):
    value = re.sub(r"\s+", " ", text.casefold()).strip(" .!?")
    return bool(
        re.fullmatch(
            r"(?:please )?(?:what(?:'s| is) )?(?:today'?s date|current date|date today|"
            r"today's date and time|current date and time|time now|current time|"
            r"local time|what time is it|what date is it)",
            value,
        )
    )


def current_datetime_reply(now=None):
    now = now or datetime.now().astimezone()
    return "Local date and time: " + now.strftime("%A, %d %B %Y, %I:%M %p %Z")


def live_news_query(text):
    value = re.sub(r"\s+", " ", text).strip(" .!?")
    normalized = value.casefold()
    live_signal = re.search(
        r"\b(?:latest|current|breaking|recent|today|right now|real[ -]?time|up to date)\b",
        normalized,
    )
    news_signal = re.search(r"\b(?:news|headlines|what(?:'s| is) happening)\b", normalized)
    if not (live_signal and news_signal):
        return None
    return value[:500]
