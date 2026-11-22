"""URLs that may be opened from untrusted source metadata in the native UI."""

from urllib.parse import unquote, urlsplit


def browser_source(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        decoded = unquote(value)
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not any(ord(char) < 32 or ord(char) == 127 for char in decoded)
            and (parsed.port is None or 0 < parsed.port < 65536)
        )
    except ValueError:
        return False
