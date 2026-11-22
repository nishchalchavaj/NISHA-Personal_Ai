"""Keep everyday dialogue at the orb; show requested reference content in glass."""

import re


def uses_results(text, previous=False):
    value = (
        re.sub(
            r"^(?:hey\s+)?(?:nisha|neesha|nishaa|nisa|meesha)[,\s]+",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )
        .casefold()
        .strip(" .!?")
    )
    if not value:
        return False
    if re.fullmatch(
        r"(?:hi|hey|hello|thanks|thank you|okay|ok|good (?:morning|evening|night)|bye|nothing|just thinking|how are you(?: doing)?(?: today)?|how (?:is|was) your day|what are you doing(?: now| today)?|tell me about yourself|what happened|are you (?:there|okay|listening)|i(?:'m| am) (?:fine|okay|thinking|sad|happy|tired|busy)|don't disturb(?: me)?|do not disturb(?: me)?|you can talk now)[,!\s]*(?:nisha|sir|boss)?",
        value,
    ):
        return False
    if re.match(
        r"^(?:my (?:name|birthday|favou?rite|hobbies|pet)|i (?:like|enjoy|love|prefer|live|work|study|feel)|call me|address me)\b",
        value,
    ):
        return False
    if re.match(
        r"^(?:please )?(?:who (?:is|was)|what (?:is|are|does|do)|where|when|why|how|explain|tell me about|information|research|compare|search|find|show (?:me )?(?:images?|pictures?|photos?|videos?|results|my emails)|read (?:my )?emails?)\b",
        value,
    ):
        return True
    if re.search(r"\b(?:write|draft|compose|create|prepare|generate)\b", value) and re.search(
        r"\b(?:email|mail|code|script|program|document|letter|essay|report|article|notes|presentation|about|on|in notepad|in word)\b",
        value,
    ):
        return True
    if re.match(
        r"^(?:/show |/preferences|/memories|/learn|/task|list installed apps|show my (?:personal profile|preferences)|approve youtube|subscribe|like (?:this|that|the) video)",
        value,
    ):
        return True
    return bool(
        previous
        and re.match(
            r"^(?:and\b|also\b|continue\b|more\b|shorter\b|tell me short|now answer|in (?:short|detail)|make it|change it|revise|send (?:it|email)|approve email|(?:the )?(?:recipient|address) is|to \S+@)",
            value,
        )
    )
