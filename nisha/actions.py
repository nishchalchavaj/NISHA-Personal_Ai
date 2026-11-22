"""Execute explicit website requests; model text never authorizes an action."""

import logging
import re
import webbrowser
from collections.abc import Callable
from urllib.parse import urlparse

WEBSITES = {
    "youtube": ("YouTube", "https://www.youtube.com/"),
    "google": ("Google", "https://www.google.com/"),
    "github": ("GitHub", "https://github.com/"),
    "gmail": ("Gmail", "https://mail.google.com/"),
    "wikipedia": ("Wikipedia", "https://www.wikipedia.org/"),
}


class WebsiteActions:
    def __init__(self, opener: Callable | None = None):
        self.opener = opener or webbrowser.open
        self.last_url = None
        from nisha.youtube import YouTubeActions

        self.youtube = YouTubeActions(self.opener)

    def handle(self, text, history, store, session=None):
        self.last_url = None
        reply = self.youtube.handle(text, history, store, session=session)
        if reply is not None:
            self.last_url = self.youtube.last_url
            return reply
        request = text.strip().casefold()
        request = re.sub(r"^(?:hey\s+)?nisha\b[,\s]*", "", request)
        match = re.fullmatch(
            r"(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
            r"(?:open|launch|start)\s+(.+?)[.!?]*",
            request,
        )
        # Whisper occasionally joins the command to a dictated domain, e.g.
        # "OpenExample.org". Accept this only for an explicit domain, never a
        # joined app name or arbitrary phrase.
        if not match:
            match = re.fullmatch(
                r"(?:open|launch|start)((?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?)[!?]*",
                request.rstrip("."),
            )
        if not match:
            return None
        target = match[1].strip()
        target = re.sub(r"\s+(?:for me|please|in (?:the |my )?browser)$", "", target)
        target = re.sub(r"^(?:the\s+)", "", target)
        target = re.sub(r"\s+(?:website|site)$", "", target)
        target = {"you tube": "youtube", "youtube.com": "youtube"}.get(target, target)
        if target in {"it", "that", "that website", "that site"}:
            target = self._recent_site(history)
        resolved = WEBSITES.get(target) or spoken_website(target)
        if not resolved:
            store.audit("open_website", "unsupported")
            return (
                "I haven't opened anything. Tell me the website address, such as example dot com, "
                "or the name of an installed app."
            )
        name, url = resolved
        try:
            opened = bool(self.opener(url, new=2))
        except Exception:
            logging.getLogger("nisha").exception("Website browser launch failed")
            opened = False
        store.audit("open_website", "browser_requested" if opened else "failed")
        if opened:
            self.last_url = url
            return f"I've asked your default browser to open {name}."
        return f"I couldn't open {name}: the browser launch failed."

    @staticmethod
    def _recent_site(history):
        for turn in reversed(history):
            # Domain references participate in follow-ups too. Refuse ambiguous
            # references rather than choosing the first site in a comparison.
            domains = re.findall(
                r"(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>]*)?",
                turn["content"].casefold(),
            )
            domains = list(dict.fromkeys(value.rstrip(".,!?;)") for value in domains))
            if domains:
                return domains[0] if len(domains) == 1 else None
            matches = [
                name
                for name in WEBSITES
                if re.search(r"\b" + re.escape(name) + r"\b", turn["content"], re.IGNORECASE)
            ]
            if matches:
                return matches[0] if len(matches) == 1 else None
        return None


def spoken_website(target):
    """Resolve dictated domains without inventing a domain for an unknown name."""
    if not isinstance(target, str):
        return None
    value = target.strip().casefold()
    if re.search(r"[\\<>\"'{};]|\.exe\b|\.bat\b|\.cmd\b", value):
        return None
    for spoken, symbol in [
        ("dot", "."),
        ("slash", "/"),
        ("dash", "-"),
        ("hyphen", "-"),
        ("underscore", "_"),
    ]:
        value = re.sub(r"\s+" + spoken + r"\s+", symbol, value)
    value = re.sub(r"^www\s+", "www.", value)
    if re.match(r"^[a-z][a-z0-9+.-]*:", value) and not value.startswith(("https://", "http://")):
        return None
    if "." in value and " " not in value:
        url = value if value.startswith(("https://", "http://")) else "https://" + value
        parsed = urlparse(url)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and re.fullmatch(r"[a-z0-9.-]+", parsed.hostname)
            and "." in parsed.hostname
        ):
            return parsed.hostname, url
        return None
    # An unfamiliar spoken name can be an installed app, folder or Windows
    # namespace. Searching Google would claim to have opened the wrong thing.
    return None
