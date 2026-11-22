"""Explicit YouTube navigation and reviewed account actions in the current browser."""

import json
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from urllib.parse import quote_plus
from uuid import uuid4

from nisha.errors import NishaError


class CurrentBrowser:
    def request(self, operation, **kwargs):
        try:
            executable = Path(sys.executable)
            if executable.name.casefold() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            result = subprocess.run(
                [str(executable), "-m", "nisha.browser_session"],
                input=json.dumps({"operation": operation, **kwargs}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=25,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(result.stdout)
            if result.returncode or payload.get("error"):
                raise NishaError(payload.get("error") or "Browser controls unavailable.")
            return payload
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise NishaError(
                "I couldn't verify YouTube controls in your current browser. Keep the YouTube tab visible and try again. No account action was confirmed."
            ) from exc


class YouTubeActions:
    def __init__(self, opener, browser=None, clock=monotonic):
        self.opener, self.browser, self.clock = opener, browser or CurrentBrowser(), clock
        self.pending = {}
        self.last_url = None

    def handle(self, text, history, store, session=None):
        self.last_url = None
        value = re.sub(r"^(?:hey\s+)?nisha\b[,\s]*", "", text.strip(), flags=re.IGNORECASE)
        value = re.sub(
            r"^(?:please\s+)?(?:(?:can|could|would) you\s+)?", "", value, flags=re.IGNORECASE
        ).strip(" .!?")
        approval = re.fullmatch(r"approve youtube ([a-f0-9]{10})", value.casefold())
        if (
            not approval
            and len(self.pending) == 1
            and value.casefold()
            in {
                "approve youtube",
                "approve youtube action",
                "yes subscribe",
                "yes like",
                "confirm youtube action",
            }
        ):
            token = next(iter(self.pending))
            if history and token in history[-1]["content"]:
                approval = re.fullmatch(
                    r"approve youtube ([a-f0-9]{10})", "approve youtube " + token
                )
        if approval:
            item = self.pending.get(approval[1])
            if item and item.get("session") != session:
                return "That YouTube approval belongs to another conversation. Review the action in this conversation first."
            item = self.pending.pop(approval[1], None)
            if not item or self.clock() > item["expires"]:
                return (
                    "That YouTube approval expired or was already used. Request the action again."
                )
            try:
                receipt = self.browser.request("apply", preview=item["preview"])
                store.audit("youtube_" + item["preview"]["action"], "verified")
                return receipt["message"]
            except NishaError as exc:
                store.audit("youtube_account_action", "unconfirmed")
                return str(exc)
        if value.casefold() in {
            "cancel youtube action",
            "cancel youtube",
            "don't subscribe",
            "do not subscribe",
        }:
            self.pending.clear()
            return "YouTube account action cancelled."
        # Restrict follow-up searches to a conversation that actually requested YouTube.
        on_youtube = any("youtube" in turn["content"].casefold() for turn in history[-4:])
        search = re.fullmatch(
            r"(?:open|launch|start) (?:you\s*tube)(?: (?:and |then )?(?:search|find|look for)(?: for)? (.+))?",
            value,
            re.IGNORECASE,
        )
        if not search:
            search = re.fullmatch(
                r"(?:search|find|look for)(?: for)? (.+?) (?:on|in) (?:you\s*tube)",
                value,
                re.IGNORECASE,
            )
        if not search and on_youtube:
            search = re.fullmatch(r"(?:search|find|look for)(?: for)? (.+)", value, re.IGNORECASE)
        action = None
        query = search[1] if search and search.lastindex else None
        if query:
            ending = re.search(
                r"\s+(?:and|then)\s+(subscribe(?: to (?:it|the channel))?|like(?: (?:it|the video))?)$",
                query,
                re.IGNORECASE,
            )
            if ending:
                action = "subscribe" if ending[1].casefold().startswith("subscribe") else "like"
                query = query[: ending.start()]
            query = re.sub(
                r"^(?:the )?channel\s+|\s+channel$", "", query, flags=re.IGNORECASE
            ).strip()
            if not 1 <= len(query) <= 200:
                return "Give me a shorter YouTube search phrase."
            url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
            if action == "subscribe":
                url += "&sp=EgIQAg%253D%253D"  # YouTube's Channels filter
            try:
                opened = bool(self.opener(url, new=2))
            except (OSError, ValueError):
                opened = False
            if not opened:
                return "I couldn't open the YouTube search in your current browser."
            self.last_url = url
            store.audit("youtube_search", "browser_requested")
            if not action:
                return f"I've asked your default browser to search YouTube for {query}."
            if action == "like":
                return f"Opened the YouTube search for {query}. Choose the intended video, then say 'like this video' to review its exact page before approval."
            try:
                self.browser.request("select_channel", target=query)
            except NishaError as exc:
                return f"Opened the YouTube search for {query}. " + str(exc)
        elif search:
            # Let the existing website handler preserve plain 'open YouTube'.
            return None
        else:
            mutation = re.fullmatch(
                r"(subscribe)(?: to (?:this|that|the) channel)?|(?:like)(?: (?:this|that|the) video| it)?",
                value,
                re.IGNORECASE,
            )
            named = re.fullmatch(r"subscribe to (.+?)(?: on youtube)?", value, re.IGNORECASE)
            if mutation:
                action = "subscribe" if mutation[1] else "like"
            elif named:
                target = re.sub(r"\s+channel$", "", named[1], flags=re.IGNORECASE)
                try:
                    self.browser.request("select_channel", target=target)
                except NishaError as exc:
                    return str(exc)
                action = "subscribe"
            else:
                return None
        try:
            preview = self.browser.request("preview", action=action)
        except NishaError as exc:
            return str(exc)
        if preview.get("already"):
            return preview["message"]
        token = uuid4().hex[:10]
        self.pending.clear()
        self.pending[token] = {
            "preview": preview,
            "expires": self.clock() + 180,
            "session": session,
        }
        store.audit("youtube_account_action", "awaiting_review")
        return f"Review YouTube action: {action} — {preview['title']}\nPage: {preview['url']}\nSay 'approve youtube action' to do exactly this, or 'cancel youtube action'. Approval: {token}"
