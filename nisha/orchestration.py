"""Split explicit chained user actions into ordered, individually routed steps."""

import re

_ACTION = re.compile(
    r"\b(?:close|minimi[sz]e|maximi[sz]e|open|launch|start|play|resume|"
    r"check|show|list|read|draft|compose|write|prepare|search|find|look for|"
    r"type|save|edit|revise|rewrite|send|delete|remove|click|tap|select|press|scroll|"
    r"focus|activate|switch to|go to|turn on|turn off)\b",
    re.IGNORECASE,
)
_JOIN = re.compile(r"(?:,|;|\bthen\b|\band then\b|\band\b|\bafter that\b|\bnext\b|\bso\b)", re.IGNORECASE)
_ACTION_PREFIX = re.compile(
    r"\s*(?:(?:please|can you|could you|would you|will you|hey\s+nisha|by the way|by the)\s*,?\s*)*",
    re.IGNORECASE,
)


def split_compound(text):
    """Return clear action clauses in order; leave ordinary prose untouched."""
    value = re.sub(r"\s+", " ", text).strip()
    if not value or len(value) > 5000:
        return []
    from nisha.browser_commands import chrome_first_result_request, chrome_youtube_video_request
    from nisha.music import spotify_request

    if chrome_first_result_request(value) or chrome_youtube_video_request(value):
        return []
    # Spotify owns its own open/search/play flow; splitting it loses the target app
    # and the requested track or mood between steps.
    if spotify_request(value):
        spotify_at = value.casefold().find("spotify")
        before = value[:spotify_at]
        before = re.sub(
            r"(?:\b(?:so\s+)?(?:play|put on|start)\b.+\b(?:in|on)\s*)$",
            "",
            before,
            flags=re.IGNORECASE,
        )
        before = re.sub(r"\b(?:open|launch|start)\s*$", "", before, flags=re.IGNORECASE)
        after = value[spotify_at + len("spotify") :]
        later_command = re.search(
            r"(?:,|;|\bthen\b|\band\b)\s*(?:by the\s+)?"
            r"(?:check|write|draft|compose|close|minimi[sz]e|maximi[sz]e|"
            r"search|find|read|send|delete|remove|switch|go to|open)\b",
            after,
            re.IGNORECASE,
        )
        if not _ACTION.search(before) and not later_command:
            return []
    if re.fullmatch(
        r"(?:please )?(?:open|launch|start) (?:google )?chrome "
        r"(?:(?:and|then) )?(?:search|find|look for)(?: for)? .{1,200}",
        value,
        re.IGNORECASE,
    ):
        return []
    if re.match(r"^(?:please )?(?:open|launch|start) you\s*tube\b", value, re.IGNORECASE) and re.search(
        r"\b(?:and|then)?\s*(?:search|find|look for)\b", value, re.IGNORECASE
    ):
        return []

    # Actions after connectors are explicit steps. Permit a short natural-language
    # preface before a final "so <action>" (e.g. a stressed user asking for music).
    starts = []
    previous_end = 0
    for match in _ACTION.finditer(value):
        if match.group().casefold() == "draft" and re.search(
            r"\bin\s+$", value[: match.start()], re.IGNORECASE
        ):
            previous_end = match.end()
            continue
        prefix = value[: match.start()]
        between = value[previous_end : match.start()]
        connectors = list(_JOIN.finditer(between))
        connected = bool(
            connectors
            and _ACTION_PREFIX.fullmatch(between[connectors[-1].end() :])
        )
        if (
            not prefix.strip()
            or (
                not starts
                and _ACTION_PREFIX.fullmatch(prefix)
            )
            or connected
        ) or not starts and re.search(r"\bso\s+$", prefix, re.IGNORECASE):
            starts.append(match.start())
        previous_end = match.end()
    if not starts:
        return []

    clauses = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(value)
        clause = value[start:end].strip(" ,;.!?\t")
        clause = re.sub(
            r"(?:\s+\b(?:and|then|after that|next|by the)\b)+\s*$", "", clause, flags=re.IGNORECASE
        ).strip()
        if clause:
            clauses.append(clause)
    if len(clauses) >= 2:
        return clauses[:8]
    # A single clear action following conversational preamble is still routed as
    # an action. Mere mentions inside a sentence do not satisfy the connector rule.
    start = starts[0]
    prefix = value[:start]
    if start > 0 and _JOIN.search(prefix):
        connector = list(_JOIN.finditer(prefix))[-1]
        connector_text = connector.group().casefold()
        if connector_text in {"so", ",", ";", "after that", "next"} and _ACTION_PREFIX.fullmatch(
            prefix[connector.end() :]
        ):
            # Keep the natural-language preface attached to its single action;
            # adapters may need that context (for example, email content or mood).
            return [value]
    return []
