"""Isolated, bounded accessibility adapter for existing Edge/Chrome tabs.

No private profile copying, browser restart, debugger port, arbitrary scripts,
login automation or model-generated clicks. Invocations use observed browser
controls and verify the destination before reporting success.
"""

import json
import os
import re
import sys
from time import monotonic, sleep
from urllib.parse import parse_qs, urlparse


def normalized(text):
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def youtube_url(value):
    value = value.strip()
    if not value.startswith("https://"):
        value = "https://" + value
    parsed = urlparse(value)
    return (
        value
        if parsed.scheme == "https"
        and parsed.hostname in {"youtube.com", "www.youtube.com"}
        and not parsed.username
        and not parsed.password
        else None
    )


def same_youtube_page(actual, expected):
    a, e = urlparse(actual), urlparse(expected)
    if a.hostname not in {"youtube.com", "www.youtube.com"} or e.hostname not in {
        "youtube.com", "www.youtube.com"
    } or a.path.rstrip("/").casefold() != e.path.rstrip("/").casefold():
        return False
    if e.path == "/watch":
        return parse_qs(a.query).get("v") == parse_qs(e.query).get("v")
    if e.path == "/results":
        return parse_qs(a.query).get("search_query") == parse_qs(e.query).get("search_query")
    return True


class SessionControls:
    def __init__(self, windows=None):
        self.dynamic_windows = windows is None
        if windows is None:
            from pywinauto import Desktop

            windows = Desktop(backend="uia").windows()
        self.windows = windows

    @staticmethod
    def address(window):
        for edit in window.descendants(control_type="Edit"):
            try:
                value = edit.get_value().strip()
            except (AttributeError, ValueError):
                continue
            if value:
                parsed = urlparse(value if "://" in value else "https://" + value)
                if parsed.hostname:
                    return parsed
        return None

    def google_search_page(self, browser, query):
        if self.dynamic_windows:
            from pywinauto import Desktop

            self.windows = Desktop(backend="uia").windows()
        matches = []
        for window in self.windows:
            try:
                if not self.is_browser(window, browser):
                    continue
                address = self.address(window)
                if not address or address.path != "/search":
                    continue
                host = address.hostname.casefold()
                if not (host == "google.com" or host.startswith("www.google.")):
                    continue
                searched = parse_qs(address.query).get("q", [""])[0]
                if normalized(searched) != normalized(query):
                    continue
                documents = [
                    doc for doc in window.descendants(control_type="Document")
                    if doc.is_visible() and "google search" in doc.window_text().casefold()
                ]
                if len(documents) == 1:
                    matches.append((window, documents[0]))
            except (AttributeError, ValueError):
                continue
        if len(matches) != 1:
            raise ValueError("I couldn't identify one matching Google search tab in that browser.")
        return matches[0]

    def open_google_first_result(self, browser, query, target=""):
        if browser not in {"chrome", "edge"} or not 1 <= len(query) <= 200:
            raise ValueError("Name a recent browser search to open its first result.")
        deadline = monotonic() + 10
        while monotonic() < deadline:
            try:
                window, document = self.google_search_page(browser, query)
                break
            except ValueError:
                sleep(0.25)
        else:
            raise ValueError("The matching Google search tab did not appear in that browser.")
        requested = normalized(target or query)
        official = (
            "youtube.com" if "youtube" in requested.replace(" ", "")
            else "whatsapp.com" if "whatsapp" in requested.replace(" ", "")
            else None
        )
        candidates = []
        for link in document.descendants(control_type="Hyperlink"):
            try:
                if not link.is_visible():
                    continue
                url = link.legacy_properties().get("Value", "").strip()
                parsed = urlparse(url)
                host = (parsed.hostname or "").casefold()
                if parsed.scheme != "https" or not host or parsed.username or parsed.password:
                    continue
                if host == "google.com" or host.endswith(".google.com") or host.startswith("www.google."):
                    continue
                if official and host != official and not host.endswith("." + official):
                    continue
                label = link.window_text().strip()
                if target and not official and normalized(target) not in normalized(label):
                    continue
                candidates.append((link, label, url, host))
            except (AttributeError, ValueError):
                continue
        if not candidates:
            raise ValueError("I couldn't identify a matching result link on the visible Google page.")
        link, label, selected_url, host = candidates[0]
        link.invoke()
        deadline = monotonic() + 6
        while monotonic() < deadline:
            try:
                current = self.address(window)
                current_host = (current.hostname or "").casefold() if current else ""
                if current and current_host == host or current_host.endswith("." + host):
                    return {"title": label[:160], "url": current.geturl(), "browser": browser}
            except (AttributeError, ValueError):
                pass
            sleep(0.2)
        raise ValueError(
            f"I clicked {selected_url}, but couldn't verify the destination in {browser}."
        )

    def page(self, browser=None, expected_url=None):
        candidates = []
        for window in self.windows:
            if "youtube" not in window.window_text().casefold():
                continue
            # Restrict to actual browser executable, not another app titled YouTube.
            if not self.is_browser(window, browser):
                continue
            descendants = window.descendants()
            first_document = next(
                (i for i, item in enumerate(descendants) if item.element_info.control_type == "Document"),
                len(descendants),
            )
            # Chrome exposes the URL itself as the address Edit's name. Only
            # inspect browser chrome before the document, never page-owned inputs.
            edits = [
                item for item in descendants[:first_document]
                if item.element_info.control_type == "Edit"
            ]
            documents = [
                doc for doc in window.descendants(control_type="Document")
                if "youtube" in doc.window_text().casefold() and doc.is_visible()
            ]
            if len(documents) != 1:
                continue
            for edit in edits:
                try:
                    url = youtube_url(edit.get_value())
                except (AttributeError, ValueError):
                    continue
                if url and (expected_url is None or same_youtube_page(url, expected_url)):
                    candidates.append((window, documents[0], url))
        if len(candidates) != 1:
            raise ValueError(
                "I couldn't uniquely identify the requested YouTube tab in the selected browser. Keep it visible and try again; no page action was confirmed."
            )
        return candidates[0]

    @staticmethod
    def is_browser(window, browser=None):
        import psutil

        name = psutil.Process(window.process_id()).name().casefold()
        return name == ("chrome.exe" if browser == "chrome" else "msedge.exe") if browser else name in {"msedge.exe", "chrome.exe"}

    def wait_page(self, browser, expected_url, deadline):
        while monotonic() < deadline:
            try:
                return self.page(browser=browser, expected_url=expected_url)
            except ValueError:
                sleep(0.25)
        raise ValueError("The requested YouTube page did not become visible in Chrome.")

    def play_channel_video(self, browser, target):
        if browser != "chrome" or not 1 <= len(target) <= 100:
            raise ValueError("Choose an exact channel name in Chrome.")
        deadline = monotonic() + 20
        query = normalized(target)
        compact = query.replace(" ", "")
        results = None
        while monotonic() < deadline:
            try:
                _, results, url = self.page(browser="chrome")
                parsed = urlparse(url)
                if parsed.path == "/results" and normalized(
                    parse_qs(parsed.query).get("search_query", [""])[0]
                ) == query:
                    break
            except ValueError:
                pass
            sleep(0.25)
        else:
            raise ValueError("The requested channel search did not appear in Chrome.")
        matches = []
        while monotonic() < deadline:
            handle_matches, name_matches = {}, {}
            _, results, url = self.page(browser="chrome")
            parsed = urlparse(url)
            if parsed.path != "/results" or normalized(
                parse_qs(parsed.query).get("search_query", [""])[0]
            ) != query:
                raise ValueError("The Chrome tab changed before I selected the channel.")
            for link in results.descendants(control_type="Hyperlink"):
                if not link.is_visible():
                    continue
                try:
                    channel_url = youtube_url(link.legacy_properties().get("Value", ""))
                except (AttributeError, ValueError):
                    continue
                if not channel_url or not urlparse(channel_url).path.startswith("/@"):
                    continue
                handle = urlparse(channel_url).path[2:].casefold()
                label = normalized(link.window_text().split("@", 1)[0])
                label = re.sub(r"\s+verified$", "", label)
                if handle == compact:
                    if channel_url not in handle_matches or link.window_text().strip():
                        handle_matches[channel_url] = (link, channel_url)
                elif label == query and (
                    channel_url not in name_matches or link.window_text().strip()
                ):
                    name_matches[channel_url] = (link, channel_url)
            matches = list((handle_matches or name_matches).values())
            if matches:
                break
            sleep(0.25)
        if len(matches) != 1:
            raise ValueError("I couldn't identify one exact matching channel in Chrome.")
        channel_link, channel_url = matches[0]
        channel_link.invoke()
        self.wait_page("chrome", channel_url, deadline)
        videos_url = channel_url.rstrip("/") + "/videos"
        while monotonic() < deadline:
            _, document, current_url = self.page(browser="chrome")
            if same_youtube_page(current_url, videos_url):
                break
            if not same_youtube_page(current_url, channel_url):
                raise ValueError("The Chrome tab changed before I selected Videos.")
            tabs = [
                tab for tab in document.descendants(control_type="TabItem")
                if normalized(tab.window_text()) == "videos" and tab.is_visible()
            ]
            if len(tabs) != 1:
                raise ValueError("The channel's Videos tab was not uniquely visible.")
            tabs[0].select()
            sleep(0.35)
        else:
            raise ValueError("The channel's Videos tab did not open in Chrome.")
        videos = []
        while monotonic() < deadline:
            _, document, _ = self.page(browser="chrome", expected_url=videos_url)
            found = {}
            for link in document.descendants(control_type="Hyperlink"):
                if not link.is_visible():
                    continue
                try:
                    video_url = youtube_url(link.legacy_properties().get("Value", ""))
                except (AttributeError, ValueError):
                    continue
                if (
                    video_url
                    and urlparse(video_url).path == "/watch"
                    and parse_qs(urlparse(video_url).query).get("v")
                    and (video_url not in found or link.window_text().strip())
                ):
                    found[video_url] = (link, video_url)
            videos = list(found.values())
            if videos:
                break
            sleep(0.25)
        if not videos:
            raise ValueError("No video was visible on that channel's Videos tab.")
        video_link, video_url = videos[0]
        title = video_link.window_text().strip()[:180] or "a video"
        video_link.invoke()
        _, watch_document, _ = self.wait_page("chrome", video_url, deadline)
        # Autoplay may be blocked. Prefer the observed player state to a click receipt.
        buttons = watch_document.descendants(control_type="Button")
        pauses = [
            b for b in buttons
            if re.match(r"^pause(?:\b|$)", normalized(b.window_text())) and b.is_visible()
        ]
        if not pauses:
            plays = [
                b for b in buttons
                if re.match(r"^play(?:\b|$)", normalized(b.window_text())) and b.is_visible()
            ]
            if len(plays) != 1:
                raise ValueError("The video page opened, but I couldn't verify playback.")
            plays[0].invoke()
            until = monotonic() + 3
            while monotonic() < until:
                _, watch_document, _ = self.page(browser="chrome", expected_url=video_url)
                if any(
                    re.match(r"^pause(?:\b|$)", normalized(b.window_text())) and b.is_visible()
                    for b in watch_document.descendants(control_type="Button")
                ):
                    break
                sleep(0.2)
            else:
                raise ValueError("The video page opened, but YouTube didn't confirm playback.")
        return {"title": title, "channel": target, "url": video_url}

    @staticmethod
    def state(button, action):
        name = normalized(button.window_text())
        if action == "subscribe":
            return name in {"subscribed", "unsubscribe"} or name.startswith(
                ("subscribed ", "unsubscribe from ")
            )
        if name.startswith(("unlike", "remove like")):
            return True
        try:
            return button.get_toggle_state() == 1
        except Exception:  # noqa: BLE001 - UIA optional pattern raises vendor-specific COM errors
            return False

    def inspect(self, action):
        if action not in {"subscribe", "like"}:
            raise ValueError("Unsupported YouTube action.")
        _, document, url = self.page()
        parsed = urlparse(url)
        if action == "subscribe" and not re.match(r"/(?:@|channel/|c/|user/)", parsed.path):
            raise ValueError(
                "Open the intended channel page in YouTube first, then say subscribe. Search results aren't a verified channel target."
            )
        if action == "like" and (
            parsed.path != "/watch" or not re.search(r"(?:^|&)v=", parsed.query)
        ):
            raise ValueError("Open the intended video in YouTube first, then say like this video.")
        buttons = document.descendants(control_type="Button")
        if action == "subscribe":
            matches = [
                b
                for b in buttons
                if normalized(b.window_text()) in {"subscribe", "subscribed", "unsubscribe"}
                or normalized(b.window_text()).startswith(
                    ("subscribe to", "subscribed ", "unsubscribe from ")
                )
            ]
        else:
            matches = [
                b
                for b in buttons
                if re.match(
                    r"^(?:like this video|like|unlike|remove like)(?:\b|$)",
                    normalized(b.window_text()),
                )
            ]
        matches = [b for b in matches if b.is_visible() and b.is_enabled()]
        if len(matches) != 1:
            raise ValueError(
                "I couldn't uniquely identify that YouTube control. No account action was performed."
            )
        button = matches[0]
        return {
            "action": action,
            "url": url,
            "title": document.window_text(),
            "already": self.state(button, action),
            "message": "YouTube already shows this channel as subscribed."
            if action == "subscribe"
            else "YouTube already shows this video as liked.",
        }, button

    def preview(self, action):
        return self.inspect(action)[0]

    def apply(self, preview):
        current, button = self.inspect(preview["action"])
        if current["url"] != preview["url"] or current["title"] != preview["title"]:
            raise ValueError(
                "The YouTube page changed after review. Request and review the action again."
            )
        if current["already"]:
            return {"message": current["message"]}
        button.invoke()
        deadline = monotonic() + 5
        while monotonic() < deadline:
            try:
                updated, _ = self.inspect(preview["action"])
                if updated["url"] == preview["url"] and updated["already"]:
                    return {
                        "message": "YouTube confirmed the subscription."
                        if preview["action"] == "subscribe"
                        else "YouTube confirmed the like."
                    }
            except ValueError:
                pass
            sleep(0.25)
        raise ValueError(
            "I requested the action, but YouTube didn't confirm it. Check the page for a sign-in prompt or changed control; I won't retry automatically."
        )

    def select_channel(self, target):
        deadline = monotonic() + 8
        while monotonic() < deadline:
            try:
                _, document, url = self.page()
                if urlparse(url).path != "/results":
                    raise ValueError("Open a YouTube channel search first.")
                links = [
                    link
                    for link in document.descendants(control_type="Hyperlink")
                    if normalized(link.window_text()) == normalized(target) and link.is_visible()
                ]
                if len(links) == 1:
                    links[0].invoke()
                    sleep(0.5)
                    current = self.preview("subscribe")
                    if normalized(target) not in normalized(current["title"]):
                        raise ValueError("The opened channel doesn't match the requested name.")
                    return {"message": "Channel page verified.", "url": current["url"]}
            except ValueError:
                pass
            sleep(0.3)
        raise ValueError(
            "I couldn't identify one exact matching channel. Choose the intended channel in the YouTube results, then say subscribe."
        )


def main():
    try:
        if os.name != "nt":
            raise ValueError("Current-browser controls require Windows.")
        request = json.loads(sys.stdin.read(16000))
        controls = SessionControls()
        operation = request["operation"]
        if operation == "preview":
            result = controls.preview(request["action"])
        elif operation == "apply":
            result = controls.apply(request["preview"])
        elif operation == "select_channel":
            result = controls.select_channel(request["target"])
        elif operation == "play_channel_video":
            result = controls.play_channel_video(request["browser"], request["target"])
        elif operation == "open_google_first_result":
            result = controls.open_google_first_result(
                request["browser"], request["query"], request.get("target", "")
            )
        else:
            raise ValueError("Unsupported browser operation.")
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:  # noqa: BLE001 - isolated helper must return a JSON error for COM failures
        print(json.dumps({"error": str(exc) or type(exc).__name__}, ensure_ascii=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
