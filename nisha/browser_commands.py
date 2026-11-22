"""Parse explicit multi-step browser commands without guessing account actions."""

import re


def first_result_request(text):
    """A visible Google result follow-up, optionally naming its intended site."""
    value = re.sub(r"\s+", " ", text).strip(" .!?")
    match = re.fullmatch(
        r"(?:please )?(?:click|open|go to|select) (?:on )?(?:the )?"
        r"(?:first|top|first top) (?:link|result)"
        r"(?: which (?:shows|says|is) (.+))?",
        value, re.IGNORECASE,
    )
    return match[1].strip() if match and match[1] else "" if match else None


def chrome_first_result_request(text):
    """Parse a full Chrome search-and-open instruction before model routing."""
    value = re.sub(r"\s+", " ", re.sub(r"[,;:]+", " ", text)).strip(" .!?")
    match = re.fullmatch(
        r"(?:please )?(?:open|opem|launch|start) (?:google )?chrome "
        r"(?:(?:and|then) )?(?:search|find|look for)(?: for)? (.+?) "
        r"(?:(?:and|then) )?(?:go to|open|click(?: on)?) "
        r"(?:the )?(?:first top|first|top) (?:result|link)"
        r"(?: (?:(?:and|then) )?click(?: on)? (?:the )?(?:first|top) (?:link|result))?",
        value, re.IGNORECASE,
    )
    return match[1].strip() if match else None


def chrome_youtube_video_request(text):
    value = re.sub(r"\s+", " ", re.sub(r"[,;:]+", " ", text)).strip(" .!?")
    match = re.fullmatch(
        r"(?:please )?(?:open|launch|start) (?:google )?chrome "
        r"(?:(?:and|then) )?(?:search(?: for)?|open|go to) you\s*tube "
        r"(?:(?:and|then) )?(?:(?:in|on) you\s*tube )?"
        r"(?:search|find|look for)(?: for)? (?P<channel>.+?) "
        r"(?:channel )?(?:and|then) play (?:any|a|one|the first) video"
        r"(?: from (?:the|that) channel)?",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    channel = match["channel"].strip(" .!?")
    return channel if 1 <= len(channel) <= 100 and not re.search(r"[\r\n\x00]", channel) else None
