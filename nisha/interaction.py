"""Local personal facts and restrained, opt-out conversational check-ins."""

import re
from random import choice
from time import monotonic

from nisha.storage import now

QUIET_PHRASES = {
    "don't disturb",
    "do not disturb",
    "don't disturb me",
    "do not disturb me",
    "leave me alone",
    "give me some space",
    "don't speak",
    "do not speak",
    "don't talk",
    "do not talk",
    "don't say any word",
    "don't say a word",
    "don't say anything",
    "just be quiet",
    "be quiet",
    "be silent",
    "you have to be silent",
}
RESUME_PHRASES = {
    "you can talk now",
    "let's talk",
    "lets talk",
    "keep me company",
    "enable check ins",
}

QUIET_REPLY = "I'll be here. Talk to me when you're free."
CHECKIN_PHRASES = (
    "Hey Boss, what's up?",
    "Boss, feel like talking?",
    "What's on your mind, Boss?",
    "Need a hand with anything?",
    "Want to talk about something different?",
    "I'm here, Boss. Anything you'd like to chat about?",
    "Shall we pick a topic and talk?",
    "Hey Boss, how's your day going?",
    "Want some company while you think?",
    "Got something you'd like to figure out together?",
    "Still there, Boss?",
    "Feel like taking a little break and chatting?",
    "Need me for anything, Boss?",
)


def person_name(value):
    """Accept short names, never a fragment of a misheard sentence."""
    name = value.strip(" ,.!?")
    words = name.split()
    if not 1 <= len(words) <= 3 or not re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,49}", name):
        return None
    if any(word.casefold() in {"mine", "my", "name", "not", "just", "friend", "friends", "is", "was", "he", "she", "they", "him", "her", "them", "it"} for word in words):
        return None
    return name


def friend_statement(text):
    """Only a direct named relationship; pronouns and bare names are ambiguous."""
    value = text.strip(" ,.!?")
    patterns = (
        r"(?:okay[, ]+|then[, ]+)?(?:my friend(?:'s)? name is|my friend is|one more friend is|another friend is) (.+)",
        r"(?:(?:then|wait|leave it)[, ]+)?(.+?) is (?:also )?my (?:(best|male|female|college|new) )?friend",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if not match:
            continue
        raw_name = match[1]
        name = person_name(raw_name)
        if name:
            role = match[2].casefold() if match.lastindex == 2 and match[2] else "friend"
            return name, role
    return None


def friend_name_request(text):
    """Recognize short name-list questions without treating other talk as a draft."""
    words = re.findall(r"[a-z']+", text.casefold())
    allowed = {
        "tell", "me", "just", "all", "my", "friend", "friends", "friend's",
        "name", "names", "there", "who", "are", "do", "you", "know", "to",
        "the", "what", "is", "male", "female", "best", "please", "list",
    }
    return bool(
        words
        and all(word in allowed for word in words)
        and any(word in {"friend", "friends", "friend's"} for word in words)
        and (
            any(word in {"name", "names", "all", "best", "male", "female"} for word in words)
            or words[:2] in (["who", "are"], ["what", "are"], ["do", "you"])
        )
    )


def is_quiet_request(text):
    normalized = re.sub(r"\s+", " ", text.casefold().replace("’", "'")).strip(" ,.!?")
    normalized = normalized.replace("dont ", "don't ")
    return normalized.removeprefix("please ") in QUIET_PHRASES


def is_silent_request(text):
    """A direct request for no spoken acknowledgement, unlike 'don't disturb'."""
    normalized = re.sub(r"\s+", " ", text.casefold().replace("’", "'")).strip(" ,.!?")
    return normalized.removeprefix("please ") in {
        "don't speak", "do not speak", "don't talk", "do not talk",
        "don't say any word", "don't say a word", "don't say anything",
        "be silent", "you have to be silent",
    }


class Interaction:
    def __init__(self, store):
        self.store = store

    @property
    def quiet(self):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT value FROM preferences WHERE key='interaction_quiet'"
            ).fetchone()
            return bool(row and row["value"] == "true")

    def set_quiet(self, value):
        with self.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO preferences VALUES('interaction_quiet',?,?,1,?)",
                ("true" if value else "false", "Direct user instruction", now()),
            )

    def profile(self):
        return [
            m
            for m in self.store.memories()
            if m["category"] in {"personal_profile", "personal_event"}
        ]

    def observe(self, text):
        if re.match(
            r"^(?:/|(?:please )?(?:(?:can|could|would|will) you |i want (?:you )?to )?(?:write|draft|compose|create|prepare|learn|remember)\b)",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"\b(?:example|pretend|suppose|imagine|if i|password|passcode|otp|api key|secret|bank|credit card)\b",
            text,
            re.IGNORECASE,
        ):
            return []
        direct = re.sub(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`|(?<!\w)\'[^\'\n]*\'(?!\w)', "", text)
        correction = re.fullmatch(
            r"my name is not .+?,?\s+(?:it's|it is|my name is) (.+?)[.!]*",
            direct.strip(),
            re.IGNORECASE,
        )
        if correction:
            direct = "My name is " + correction[1]
        patterns = [
            ("name", r"my name is (.+)", "User's name is {}."),
            ("address_as", r"(?:call|address) me (.+)", "User wants to be addressed as {}."),
            ("city", r"i (?:live in|am from|come from) (.+)", "User's home city/region is {}."),
            ("work", r"i (?:work as|am working as) (.+)", "User works as {}."),
            ("birthday", r"my birthday is (.+)", "User's birthday is {}."),
            ("favorite_color", r"my favou?rite colou?r is (.+)", "User's favorite color is {}."),
            ("favorite_food", r"my favou?rite food is (.+)", "User's favorite food is {}."),
            ("interests", r"i (?:like|love|enjoy) (.+)", "User enjoys {}."),
            ("dislikes", r"i (?:dislike|hate|don't like|do not like) (.+)", "User dislikes {}."),
            ("personal_preference", r"i prefer (.+)", "User prefers {}."),
            ("study", r"i (?:study|am studying) (.+)", "User studies {}."),
            ("hobbies", r"my hobbies (?:are|include) (.+)", "User's hobbies include {}."),
            ("pet", r"my pet(?:'s)? name is (.+)", "User's pet is named {}."),
        ]
        saved = []
        for sentence in re.split(r"[.!?\n]", direct):
            if fact := friend_statement(sentence):
                name, role = fact
                label = "best friend" if role == "best" else f"{role} friend" if role != "friend" else "friend"
                memory = f"User says {name} is a {label}."
                self.store.remember(
                    memory,
                    key="profile:friend:" + re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_"),
                    category="personal_profile",
                    cloud_allowed=False,
                )
                saved.append(memory)
        for sentence in re.split(r"[.!\n]|\s+and (?=(?:I |my ))", direct, flags=re.IGNORECASE)[:8]:
            sentence = re.sub(
                r"^(?:actually|by the way|nisha)[,\s]+", "", sentence.strip(), flags=re.IGNORECASE
            )
            for key, pattern, template in patterns:
                match = re.fullmatch(pattern, sentence, re.IGNORECASE)
                if not match:
                    continue
                value = match[1].strip(" ,")
                if key == "name":
                    value = person_name(value)
                    if value is None:
                        continue
                if (
                    not 1 <= len(value) <= 120
                    or "?" in value
                    or re.search(r"[<>@\\/]|\d{7,}", value)
                ):
                    continue
                if key == "city" and re.search(r"\d", value):
                    continue
                memory = template.format(value)
                self.store.remember(
                    memory, key="profile:" + key, category="personal_profile", cloud_allowed=False
                )
                saved.append(memory)
                break
        return saved

    def handle(self, text):
        value = text.casefold().strip(" .!?")
        value = re.sub(r"[,\s]+nisha$", "", value)
        if friend_name_request(value):
            friends = [
                (
                    item["text"].removeprefix("User says ").split(" is a ", 1)[0],
                    item["text"].split(" is a ", 1)[-1].rstrip("."),
                )
                for item in reversed(self.store.memories())
                if (item["key"] or "").startswith("profile:friend:")
            ]
            if not friends:
                return "I don't have your friends' names saved yet."
            words = set(re.findall(r"[a-z']+", value))
            if "best" in words and "male" in words:
                known = [name for name, role in friends if {"best", "male"} <= set(role.split())]
                if known:
                    return "Best male friends you named: " + ", ".join(dict.fromkeys(known)) + "."
                best = [name for name, role in friends if "best" in role.split()]
                male = [name for name, role in friends if "male" in role.split()]
                return (
                    "Best friends you named: " + (", ".join(best) or "none yet") + ". "
                    "You named " + (", ".join(male) or "no one")
                    + " as a male friend; I don't have genders saved for the best friends."
                )
            role = "best" if "best" in words else "male" if "male" in words else "female" if "female" in words else None
            names = [name for name, saved_role in friends if role is None or role in saved_role.split()]
            if not names:
                return "I don't have names saved for that group of friends."
            return ", ".join(dict.fromkeys(names)) + "."
        if value in {"what is my name", "what's my name", "do you know my name"}:
            name = next(
                (item["text"].removeprefix("User's name is ").rstrip(".")
                 for item in self.store.memories() if item["key"] == "profile:name"),
                None,
            )
            return name + "." if name else "I don't have your name saved yet."
        if value in {"i didn't say anything", "i did not say anything", "i wasn't talking to you"}:
            return "I may have picked up background audio. I'll wait for you to call me."
        if value in {
            "you didn't open anything",
            "it's not opening",
            "you are not opening anything",
            "it is not done yet",
            "it's not done yet",
            "not doing it",
            "you are not doing it",
        }:
            return "You're right to check. I can't confirm that action completed. Tell me the target and I'll retry it and report what Windows confirms."
        if value in {
            "what are you doing",
            "what are you doing now",
            "what are you doing today",
            "what is happening",
            "are you there",
            "are you listening",
        }:
            return "I'm here, Boss, ready to help with your next request."
        if is_quiet_request(text):
            self.set_quiet(True)
            return QUIET_REPLY
        if value in RESUME_PHRASES:
            self.set_quiet(False)
            return "I'm here. What's on your mind?"
        if value in {
            "show my personal profile",
            "what do you know about me",
            "what have you learned about me",
            "what did you learn about me",
        }:
            from nisha.preferences import Preferences

            facts = self.profile()
            style = Preferences(self.store).handle("show my preferences")
            return (
                style
                + "\nPersonal details learned locally:\n"
                + "\n".join(m["text"] for m in facts)
                if facts
                else style + "\nNo personal details learned yet."
            )
        if value in {"forget my personal profile", "forget my personal details"}:
            for item in self.profile():
                self.store.forget(item["id"])
            return "Your learned personal details have been cleared locally."
        if value in {
            "nothing",
            "nothing just thinking",
            "just thinking",
            "i'm just thinking",
            "i am just thinking",
            "nisha nothing just thinking something",
        }:
            if self.quiet:
                return "Take your time. I'm here whenever you want to talk."
            return (
                "Take your time. Want to share what's on your mind, or would you prefer some quiet?"
            )
        return None


class IdleCheckIns:
    def __init__(self, clock=monotonic, first=300, second=600, chooser=choice):
        self.clock, self.first, self.second = clock, first, second
        self.chooser = chooser
        self.last_message = None
        self.activity()

    def activity(self):
        self.last_activity = self.clock()
        self.count = 0

    def suppress(self):
        self.count = 2

    def due(self, available, quiet):
        if not available or quiet or self.count >= 2:
            return None
        delay = self.first if self.count == 0 else self.second
        if self.clock() - self.last_activity < delay:
            return None
        self.count += 1
        self.last_activity = self.clock()
        self.last_message = self.chooser(
            [message for message in CHECKIN_PHRASES if message != self.last_message]
        )
        return self.last_message
