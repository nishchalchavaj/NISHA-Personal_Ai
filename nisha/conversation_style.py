"""Bounded conversational choices and coarse context labels, not emotion inference."""

import re

CONVERSATION_ARMS = {
    "warm": "Reply naturally and warmly in one or two short sentences. Acknowledge the actual message; don't add a question just to prolong the chat. Avoid customer-service boilerplate, generic offers of assistance, or repeating your introduction.",
    "reflective": "Briefly reflect what the user actually said and respond to it. Don't infer feelings, repeat their whole message, or turn it into advice unless asked.",
    "curious": "Respond to the user's message first. If useful, add at most one gentle question grounded in what they said. Skip the question if they want quiet or just answered one.",
}


def policy_context(text):
    value = text.casefold().strip(" .!?")
    value = re.sub(r"[,\s]+(?:nisha|neesha|boss|baby|dear)$", "", value).strip(" ,")
    if re.match(
        r"^(?:/|(?:please )?(?:open|close|minimize|maximize|write|draft|compose|create|prepare|send|approve|delete|install|download|learn|remember|forget|search|find)\b)",
        value,
    ):
        return None
    if re.fullmatch(
        r"(?:hi|hey|hello|good (?:morning|evening|afternoon)|how are you(?: doing)?(?: today)?|what are you doing(?: now| today)?|what's up|tell me about yourself|i(?:'m| am) back)",
        value,
    ):
        return "social_greeting"
    # These categories require directly stated feelings, never infer from silence.
    if re.search(
        r"\bi(?:'m| am| feel| am feeling) (?:really |so |very |a bit )?(?:sad|tired|upset|angry|lonely|stressed|worried|frustrated)\b",
        value,
    ):
        return "social_support"
    if re.search(
        r"\bi(?:'m| am| feel| am feeling) (?:really |so |very )?(?:happy|excited|proud|pleased)\b",
        value,
    ):
        return "social_positive"
    if re.search(r"\b(?:code|python|software|computer|programming|algorithm)\b", value):
        return "technical"
    if re.match(r"^(?:what|why|how|who|where|when|explain|compare|tell me about)\b", value):
        return "explanation"
    return "social_chat"


def conversation_context(context):
    return bool(context and context.startswith("social_"))
