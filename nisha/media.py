"""Public-topic visual lookup and local media discovery, separate from chat memory."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from nisha.knowledge import STOPWORDS

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_TYPES = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
WIKI_HOSTS = {
    "upload.wikimedia.org",
    "thumb.wikimedia.org",
    "en.wikipedia.org",
    "commons.wikimedia.org",
}
IMAGE_HOSTS = WIKI_HOSTS | {"api.openverse.org"}


@dataclass
class MediaAsset:
    kind: str
    title: str
    location: str
    source: str = ""
    caption: str = ""


def public_topic(text):
    match = re.search(
        r"^(?:(?:please|can you|could you)\s+)?(?:who (?:is|was)|what (?:is|are)|where is|tell me about|information (?:on|about)|show (?:me )?(?:pictures?|photos?|images?|videos?) (?:of|about))\s+(.+?)[.!?]*$",
        text.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    topic = re.sub(
        r"\s+(?:in short|in detail|briefly|please)$", "", match[1], flags=re.IGNORECASE
    ).strip()
    if re.search(r"\b(?:weather|temperature|forecast)\b", topic, re.IGNORECASE):
        return None
    if not 2 <= len(topic) <= 100 or re.search(
        r"\b(my|our|your|mine|you|me|us|we|i|nisha|doing|there|this|that|password|appointment|account|email|document|file|address)\b|@|[\\/:]|\d{7,}",
        topic,
        re.IGNORECASE,
    ):
        return None
    return topic


class MediaService:
    def __init__(self, data_dir, client=None):
        self.data_dir = Path(data_dir)
        self.client = client
        self.wiki_available = True

    @staticmethod
    def local_file(filename):
        from nisha.errors import NishaError
        from nisha.file_security import local_input_path

        try:
            path = local_input_path(filename, IMAGE_TYPES | VIDEO_TYPES)
        except NishaError:
            return None
        kind = (
            "image"
            if path.suffix.casefold() in IMAGE_TYPES
            else "video"
            if path.suffix.casefold() in VIDEO_TYPES
            else None
        )
        return (
            MediaAsset(kind, path.stem.replace("_", " "), str(path), caption="Local file")
            if kind
            else None
        )

    def local_matches(self, text):
        words = {
            word
            for word in re.findall(r"\w+", text.casefold())
            if word not in STOPWORDS and len(word) > 2
        }
        assets = []
        for folder in [
            self.data_dir / "generated",
            self.data_dir / "workspace",
            self.data_dir / "media",
        ]:
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[
                :200
            ]:
                if words.intersection(re.findall(r"\w+", path.stem.casefold().replace("_", " "))):
                    asset = self.local_file(path)
                    if asset:
                        if folder.name == "generated":
                            asset.caption = "Generated media · local file"
                        assets.append(asset)
        return assets[:5]

    def find(self, text, private=False):
        if re.fullmatch(
            r"(?:what (?:are|is) you doing|how are you|are you there)[, .!?]*(?:nisha)?[ .!?]*",
            text,
            re.IGNORECASE,
        ):
            return []
        local = self.local_matches(text)
        if local:
            return local
        topic = None if private else public_topic(text)
        if not topic:
            return []
        if self.client:
            return self._public(topic, text, self.client)
        with httpx.Client(
            timeout=8,
            trust_env=False,
            headers={"User-Agent": "NISHA/0.1 personal-assistant visual-lookup"},
        ) as client:
            return self._public(topic, text, client)

    def _public(self, topic, text, client):
        wants_video = bool(re.search(r"\bvideos?\b", text, re.IGNORECASE))
        if self.wiki_available:
            try:
                if wants_video:
                    return self._videos(topic, client)
                assets = self._wiki(topic, client)
                if assets:
                    return assets
            except httpx.HTTPError:
                self.wiki_available = False
        if wants_video:
            return []
        query = topic + " portrait" if re.match(r"who (?:is|was)\b", text, re.IGNORECASE) else topic
        response = client.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 5, "mature": "false"},
        )
        response.raise_for_status()
        assets = []
        for item in response.json().get("results", []):
            image = item.get("thumbnail", "")
            parsed = urlparse(image)
            if parsed.scheme != "https" or parsed.hostname != "api.openverse.org":
                continue
            title = item.get("title") or topic
            caption = f"Related image · {item.get('creator') or 'unknown creator'} · {item.get('license', '').upper()} {item.get('license_version', '')} · Openverse"
            assets.append(
                MediaAsset("image", title, image, item.get("foreign_landing_url", ""), caption)
            )
        words = set(re.findall(r"\w+", topic.casefold())) - STOPWORDS
        # Weak matches are worse than no image, particularly for people.
        assets = [
            asset
            for asset in assets
            if words
            and len(words.intersection(re.findall(r"\w+", asset.title.casefold())))
            >= max(1, (2 * len(words) + 2) // 3)
        ]
        assets.sort(
            key=lambda item: -len(words.intersection(re.findall(r"\w+", item.title.casefold())))
        )
        return assets[:3]

    def _videos(self, topic, client):
        response = client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "generator": "search",
                "gsrsearch": topic + " filetype:video",
                "gsrnamespace": 6,
                "gsrlimit": 3,
                "prop": "imageinfo",
                "iiprop": "url|mime",
            },
        )
        response.raise_for_status()
        assets = []
        for page in response.json().get("query", {}).get("pages", []):
            info = page.get("imageinfo", [{}])[0]
            url = info.get("url", "")
            if info.get("mime", "").startswith("video/") and urlparse(url).hostname in WIKI_HOSTS:
                assets.append(
                    MediaAsset(
                        "video",
                        page.get("title", topic),
                        url,
                        "https://commons.wikimedia.org/wiki/" + quote(page.get("title", "")),
                        "Wikimedia video · muted · view source for attribution and license",
                    )
                )
        return assets

    def _wiki(self, topic, client):
        response = client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "generator": "search",
                "gsrsearch": topic,
                "gsrlimit": 3,
                "prop": "pageimages|info|pageprops",
                "inprop": "url",
                "piprop": "thumbnail|name",
                "pithumbsize": 800,
            },
        )
        response.raise_for_status()
        pages = sorted(
            response.json().get("query", {}).get("pages", []), key=lambda p: p.get("index", 99)
        )
        assets = []
        for page in pages:
            image = page.get("thumbnail", {}).get("source", "")
            parsed = urlparse(image)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in WIKI_HOSTS
                or "disambiguation" in page.get("pageprops", {})
            ):
                continue
            title = page.get("title", topic)
            words = set(re.findall(r"\w+", topic.casefold())) - STOPWORDS
            title_words = set(re.findall(r"\w+", title.casefold()))
            if not words or len(words & title_words) < max(1, (2 * len(words) + 2) // 3):
                continue
            filename = page.get("pageimage", "")
            source = (
                "https://en.wikipedia.org/wiki/File:" + quote(filename)
                if filename
                else "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
            )
            assets.append(
                MediaAsset(
                    "image",
                    title,
                    image,
                    source,
                    "Wikipedia/Wikimedia · view source for attribution and license",
                )
            )
        return assets[:3]

    def image_bytes(self, asset):
        from nisha.file_security import IMAGE_TYPES, read_local_file
        from nisha.image_security import passive_image

        if not asset.location.startswith("https://"):
            imported = read_local_file(asset.location, allowed=IMAGE_TYPES, limit=25_000_000)
            return passive_image(imported.data, imported.suffix)
        parsed = urlparse(asset.location)
        if parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS:
            raise ValueError("Unsupported image source.")
        with (
            httpx.Client(timeout=8, trust_env=False) as client,
            client.stream("GET", asset.location) as response,
        ):
            response.raise_for_status()
            data = bytearray()
            for block in response.iter_bytes():
                data.extend(block)
                if len(data) > 25_000_000:
                    raise ValueError("Image is too large.")
            return passive_image(bytes(data))
