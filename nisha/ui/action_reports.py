"""Short spoken receipts for background actions; full details stay in chat."""

import re


def spoken_action_report(reply, command=""):
    first_line = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    if not first_line:
        return "I couldn't confirm that action. The details are in the result panel."
    failed = first_line.casefold().startswith(("action failed:", "i couldn't", "i could not"))
    if first_line.casefold().startswith("action failed:"):
        first_line = first_line.split(":", 1)[1].strip()
    sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0]
    if sentence[:2].casefold() == "i ":
        report = sentence
    else:
        actions = (
            (r"^Opened\b", "I opened"),
            (r"^Closed\b", "I closed"),
            (r"^Minimized\b", "I minimized"),
            (r"^Maximized\b", "I maximized"),
            (r"^Restored\b", "I restored"),
            (r"^Focused and verified\b", "I focused and verified"),
            (r"^Focused\b", "I focused"),
            (r"^Right-clicked\b", "I right-clicked"),
            (r"^Double-clicked\b", "I double-clicked"),
            (r"^Clicked\b", "I clicked"),
            (r"^Dragged\b", "I dragged"),
            (r"^Scrolled\b", "I scrolled"),
            (r"^Verified text\b", "I entered and verified the text"),
            (r"^Saved\b", "I saved"),
            (r"^Created\b", "I created"),
        )
        report = next(
            (re.sub(pattern, replacement, sentence, count=1) for pattern, replacement in actions
             if re.match(pattern, sentence, re.IGNORECASE)),
            ("I couldn't complete the requested action: " if failed else "I completed the requested action: ")
            + sentence,
        )
        if failed and not report.startswith("I couldn't"):
            report = "I couldn't complete the requested action: " + report
    if len(sentence) > 140:
        report = report[:160].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return report
