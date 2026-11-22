"""Grounded opening of named files and folders on the actual Windows Desktop."""

import re

from nisha.errors import NishaError


def handle_desktop_item(text, history, desktop):
    if not hasattr(desktop, "find_desktop_item"):
        return None
    value = text.strip().strip(".!?")
    request = re.fullmatch(
        r"(?:please )?(?:open|show) (?:the |my )?(?:(desktop) )?(?:(file|folder|picture|image) )?(?:named )?(.+)",
        value,
        re.IGNORECASE,
    )
    if not request:
        clarification = re.fullmatch(
            r"(?:it'?s|it is) (?:a |the )?desktop (?:file|folder) named (.+)",
            value,
            re.IGNORECASE,
        )
        if not clarification:
            return None
        target = clarification[1].strip()
        if not any(
            turn["role"] == "user"
            and re.search(r"\bopen\b", turn["content"], re.IGNORECASE)
            and re.search(re.escape(target), turn["content"], re.IGNORECASE)
            for turn in history[-10:]
        ):
            return None
        location, kind = "desktop", "file"
    else:
        location, kind, target = request.groups()
        target = target.strip()
        if target.casefold() in {"desktop", "my desktop", "my pc", "this pc", "recycle bin", "downloads", "project", "my project", "youtube", "google", "gmail", "github", "wikipedia"}:
            return None
        if not (location or kind) and any(char in target for char in "/\\\x00\r\n"):
            return None
        if not (location or kind):
            # An installed app/site takes precedence over a same-named shortcut.
            app_path = getattr(desktop, "app_path", None)
            try:
                if app_path and app_path(target):
                    return None
            except (NishaError, OSError):
                pass
            from nisha.actions import spoken_website

            if spoken_website(target):
                return None
    if re.search(r"\b(?:and|then)\b", target, re.IGNORECASE):
        return None  # Compound commands have their own workflow.
    try:
        item = desktop.find_desktop_item(target)
        if item is None:
            return f"I couldn't find {target} on your Desktop." if location or kind else None
        if item.suffix.casefold() == ".lnk":
            return None  # AppCatalog handles launch shortcuts.
        path, actual = desktop.open_desktop_item(target)
    except (NishaError, OSError) as exc:
        return str(exc) if isinstance(exc, NishaError) else "Windows couldn't open that desktop item."
    if kind and kind != actual:
        return f"{path.name} is a {actual}, not a {kind}. Asked Windows to open it."
    return f"Asked Windows to open {actual} {path.name} from your Desktop."
