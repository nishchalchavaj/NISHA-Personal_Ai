"""Small, auditable dialogue state for action follow-ups and direct silence."""

import re


def strip_trailing_address(text):
    """A final 'Nisha' addresses the assistant, not the requested app/file."""
    if not re.match(r"^(?:please )?(?:open|launch|start|close|play|search|find|click|show)\b", text, re.IGNORECASE):
        return text
    return re.sub(
        r"[,\s]+(?:nisha|neesha|nishaa|nisa|meesha)[.!?]*$",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )


def resolve_followup(text, history):
    """Resolve only a nearby safe open/minimize reference; never guess a new target."""
    value = re.sub(r"\s+", " ", text.casefold()).strip(" .!?")
    opening = value in {"open", "open it", "just open it", "open please", "now open it"}
    minimizing = value in {"minimize", "minimise", "minimize it", "minimise it"}
    if not (opening or minimizing):
        return text
    for turn in reversed(history[-12:]):
        if turn["role"] != "user":
            continue
        prior = turn["content"].casefold().strip(" .!?")
        match = re.fullmatch(
            r"(?:please )?(?:open|launch|start) (?:the |my )?([a-z][a-z0-9 +.-]{0,65})",
            prior,
        )
        if not match:
            continue
        target = match[1].strip()
        if target in {"it", "that", "this", "anything"} or re.search(
            r"\b(?:exe|bat|cmd|ps1)\b|\.\.|/|\\", target
        ):
            continue
        return ("open " if opening else "minimize ") + target
    return text


def is_action_intent(text):
    """Keep imperative PC actions out of the free-form language model."""
    value = text.casefold().strip(" .!?")
    value = re.sub(r"^(?:hey\s+)?(?:nisha|neesha|nishaa|nisa|meesha)[,\s]+", "", value)
    value = re.sub(
        r"^(?:please\s+)?(?:(?:can|could|would|will) you\s+|i want (?:you )?to\s+)?",
        "",
        value,
    )
    return bool(
        re.match(
            r"^(?:show local utilities|what offline tools can you use|show available local tools|i'm bored|im bored|i am bored|entertain me|calculate|compute|convert|roll|throw|pick random|choose random|rock paper scissors|play rock paper scissors|run (?:the )?(?:tests|test suite)|lint|inspect project|list project files|search project|research project|debug last failure|analyze recent failures|create experimental version|open|launch|start|go to|close|minimi[sz]e|maximize|play|resume|bring|write|draft|compose|create|prepare|type|save|edit|revise|rewrite|send|delete|remove|empty|clear|click|tap|select|press|scroll|focus|activate|switch to|show (?:open |running )?(?:app )?windows|(?:show|list) (?:controls|buttons|installed apps|shortcuts)|list (?:open |running )?(?:app )?windows|shut\s*down|shutdown|restart|reboot|turn (?:on|off)|switch (?:on|off))\b",
            value,
        )
        or bool(
            re.search(r"\b(?:email|emails|gmail|inbox)\b", value)
            and re.search(r"\b(?:check|show|list|read|find|look|any|new|latest|recent|update|updates|display)\b", value)
        )
    )


def unsupported_action(text):
    value = text.casefold()
    if re.search(r"\b(?:shut\s*down|shutdown|restart|reboot)\b", value):
        return "I haven't changed the computer's power state. Say the exact command again if you want me to prepare it for approval."
    if re.search(r"\b(?:empty|clear|delete|remove)\b.*\brecycle bin\b", value):
        return "I haven't emptied the Recycle Bin. That requires an exact approval before deleted files are removed."
    return "I haven't done that action. Tell me the exact app, file, site or device, and I'll check what I can control."
