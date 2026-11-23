"""Fast, bounded small talk and explicit background-command detection."""

import re


def action_request(text):
    from nisha.dialogue import is_action_intent
    from nisha.listening import is_fresh_conversation_phrase

    value = re.sub(
        r"^(?:hey\s+)?(?:nisha|neesha|nishaa|nisa|meesha)[,\s]+",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    normalized = value.casefold().strip(" .!?")
    if is_fresh_conversation_phrase(value):
        return False
    if normalized in {"open learning", "close visuals", "close image", "close nisha window"}:
        return False
    if normalized in {
        "send it",
        "send email",
        "review email",
        "approve email",
    } or normalized.startswith(("approve email ", "approve youtube ", "approve youtube action")):
        return False
    if re.match(r"^(?:show|view|open) .*\b(?:cctv|cameras?)\b", normalized):
        return False
    if normalized in {
        "close", "close nisha", "close yourself", "if you are nisha close yourself",
        "close your mouth", "close you mouth",
    }:
        return False
    if re.search(r"\bweather\b", normalized) or re.search(r"\b(?:spotify|play (?:the |a |my |current |paused )*(?:song|music))\b", normalized):
        return True
    if re.match(
        r"^(?:please )?(?:can you )?(?:describe (?:my )?screen|"
        r"what(?:'s| is) on (?:my )?screen|what does (?:my )?screen show)\b",
        normalized,
    ):
        return True
    if re.match(r"^(?:please )?(?:right[ -]click|double[ -]click|drag)\b", normalized):
        return True
    if re.match(
        r"^(?:please )?(?:run (?:the )?(?:tests|test suite)|lint|inspect project|"
        r"list project files|search project)\b",
        normalized,
    ):
        return True
    return is_action_intent(value) or bool(
        re.match(r"^(?:please )?(?:run my|do (?:my|the) usual)\b", value, re.IGNORECASE)
    )


def quick_reply(text, arm="warm", previous_reply=""):
    value = text.casefold().strip(" .!?")
    value = re.sub(r"[,\s]+(?:nisha|neesha|boss|baby|dear)$", "", value).strip(" ,")
    greeting = re.fullmatch(
        r"hi|hey|hello|good (?:morning|afternoon|evening)|what(?:'s| is) up|how are you(?: doing)?(?: today)?",
        value,
    )
    if greeting:
        if arm == "curious" and "?" not in previous_reply:
            return "Hey! What's on your mind?"
        return "Hey, I'm here. Good to hear from you."
    if value in {"thanks", "thank you", "thanks nisha"}:
        return "You're welcome."
    return None
