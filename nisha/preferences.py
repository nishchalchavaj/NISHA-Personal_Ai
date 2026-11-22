"""Durable, correctable response preferences learned from direct user feedback."""

import re

from nisha.conversation_style import conversation_context, policy_context
from nisha.storage import now

VALUES = {
    "verbosity": {"brief", "detailed"},
    "focus": {"direct"},
    "language": {"English", "Hindi", "Hinglish"},
    "wording": {"simple", "technical"},
    "format": {"paragraphs", "bullets"},
    "follow_up": {"none", "gentle"},
    "tone": {"soft"},
    "address": {"Sir", "Boss", "Sir or Boss"},
}


class Preferences:
    def __init__(self, store):
        self.store = store

    def set(self, key, value, evidence):
        if key not in VALUES or value not in VALUES[key]:
            raise ValueError("Unsupported response preference.")
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO preferences VALUES(?,?,?,1,?) ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value,evidence=excluded.evidence,observations=preferences.observations+1,updated_at=excluded.updated_at",
                (key, value, evidence[:400], now()),
            )

    def all(self):
        with self.store.connect() as db:
            return {
                row["key"]: dict(row)
                for row in db.execute("SELECT * FROM preferences")
                if row["key"] in VALUES
            }

    def reset(self):
        with self.store.connect() as db:
            db.executemany("DELETE FROM preferences WHERE key=?", [(key,) for key in VALUES])

    def observe(self, text):
        # Only direct user turns are observed. Quoted examples/documents/provider
        # output never become preference instructions.
        value = re.sub(
            r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`|(?<!\w)\'[^\'\n]*\'(?!\w)', "", text.casefold()
        )
        if re.match(r"^(?:what|how|who|when|where)\b", value):
            return []
        if re.match(
            r"^(?:/|learn this:|remember this information:|(?:please )?(?:(?:can|could|would|will) you |i want (?:you )?to )?(?:write|draft|compose|create|prepare)\b)",
            value,
        ) or re.search(r"\b(?:only this answer|for this (?:answer|question|response))\b", value):
            return []
        changed = []
        if re.search(r"\b(?:call|address) me (?:as )?sir\b|\byou have to call me sir\b", value):
            self.set("address", "Sir", text)
            changed.append("address as Sir")
        if re.search(r"\b(?:call|address) me (?:as )?boss\b", value):
            self.set("address", "Boss", text)
            changed.append("address as Boss")
        if re.search(r"\b(?:sir or boss|boss or sir),? both\b|\b(?:call|address) me (?:as )?(?:sir or boss|boss or sir)\b", value):
            self.set("address", "Sir or Boss", text)
            changed.append("address as Sir or Boss")
        if (
            re.search(
                r"(?:answer|reply|respond|tell me|tell|keep (?:it|answers|replies))\b.{0,25}\b(?:short|brief|concise)\b|\btoo (?:long|verbose)\b|\bjust answer (?:what|the question)",
                value,
            )
            or re.search(
                r"\bjust do what i (?:say|ask)|\b(?:don't|do not) explain everything", value
            )
            or re.search(
                r"\bi (?:prefer|like|want) (?:short|brief|concise) (?:answers|replies|responses)\b",
                value,
            )
        ):
            self.set("verbosity", "brief", text)
            self.set("focus", "direct", text)
            changed.append("brief, direct answers")
        if re.search(
            r"\b(?:always|by default|from now on)\b.{0,60}\b(?:detail|detailed|long)\b", value
        ) or re.search(
            r"\bi (?:prefer|like|want) (?:detailed|long) (?:answers|replies|responses)\b", value
        ):
            self.set("verbosity", "detailed", text)
            changed.append("detailed answers")
        if re.search(
            r"\b(?:use|keep|explain in)\b.{0,15}\b(?:simple|easy|plain) (?:words|language|terms)\b",
            value,
        ):
            self.set("wording", "simple", text)
            changed.append("simple wording")
        if re.search(
            r"\b(?:use|give|answer in|reply in)\b.{0,15}\b(?:bullet|bullets|bullet points)\b", value
        ):
            self.set("format", "bullets", text)
            changed.append("bullet points")
        if re.search(
            r"\b(?:don't|do not|stop) (?:use|using|give|giving) bullets?(?: points)?\b|\b(?:use|answer in) paragraphs\b",
            value,
        ):
            self.set("format", "paragraphs", text)
            changed.append("paragraphs")
        match = re.search(
            r"\b(?:answer|reply|respond|speak) (?:to me )?in (english|hindi|hinglish)\b", value
        )
        if match:
            self.set("language", match[1].title(), text)
            changed.append(match[1].title())
        if value.strip(" .!?") in {
            "you can ask questions",
            "you can ask me questions",
            "gentle follow-up questions are okay",
        }:
            self.set("follow_up", "gentle", text)
            changed.append("gentle follow-up questions")
        return changed

    def style(self, text):
        prefs = {key: row["value"] for key, row in self.all().items()}
        brief = prefs.get("verbosity", "brief") != "detailed"
        value = text.casefold()
        # A request for explanation overrides brevity for one turn, not forever.
        if re.search(r"\b(?:explain|in detail|detailed|step by step|step-by-step)\b", value):
            brief = False
        if re.search(r"\b(?:short|brief|concise|just answer)\b", value):
            brief = True
        one_word = bool(re.search(
            r"\b(?:one word|single word|just tell me (?:what|the answer|this)|"
            r"only tell me (?:what|the answer|this))\b", value
        ))
        if one_word:
            brief = True
        instructions = (
            "Answer directly in at most 2-3 short sentences, normally under 60 words."
            if brief
            else "Explain this request with enough detail to be useful. Use clear steps or examples where needed."
        )
        if one_word:
            instructions = "Answer in one word when accurate; otherwise use the shortest answer that is complete."
        instructions += " If the user only corrects the response style, revise your previous answer on the same topic."
        if conversation_context(policy_context(text)):
            instructions += " This is casual conversation: a brief warm acknowledgment and at most one natural, optional question are welcome. Do not assume emotions or interrogate."
        elif brief:
            instructions += " Do not add unsolicited context, follow-up questions or offers."
        if prefs.get("follow_up") == "none":
            instructions += " Do not ask conversational follow-up questions. Answer and let the user lead. Clarification required for an action remains allowed."
        elif prefs.get("follow_up") == "gentle":
            instructions += " Ask one relevant follow-up at a time when it helps understand the user's intent; stop asking when the user says enough or wants quiet."
        if prefs.get("tone") == "soft":
            instructions += " Use a soft, respectful tone suited to NISHA's female character, while matching the situation."
        if prefs.get("address"):
            instructions += f" Address the user as {prefs['address']} when natural; avoid using the user's given name as a form of address."
        for key, choices in VALUES.items():
            if key != "verbosity" and prefs.get(key) in choices:
                instructions += f" Preferred {key}: {prefs[key]}."
        return instructions, brief

    def handle(self, text):
        normalized = text.casefold().strip(" .!?")
        if normalized in {
            "/preferences",
            "show my preferences",
            "what have you learned about me",
            "what did you learn about me",
        }:
            prefs = self.all()
            return (
                "Learned locally: "
                + (
                    ", ".join(f"{key}={row['value']}" for key, row in prefs.items())
                    or "brief answers by default; no other preferences yet"
                )
                + "."
            )
        if normalized in {"/reset-preferences", "reset my preferences", "forget my preferences"}:
            self.reset()
            return "Learned response preferences cleared. Brief answers remain the default."
        return None
