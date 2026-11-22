"""Short spoken receipts for background actions; full details stay in chat."""

import re


def spoken_action_report(reply):
    first_line = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    if not first_line:
        return "I couldn't confirm that action. Check the chat."
    if first_line.casefold().startswith("action failed:"):
        first_line = first_line.split(":", 1)[1].strip()
    sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0]
    if len(sentence) > 140:
        sentence = sentence[:140].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return sentence
