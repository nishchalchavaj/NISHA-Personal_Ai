"""Read the local transcript and action receipts; never execute transcript commands."""

import html
import sqlite3
from collections import Counter
from datetime import UTC, datetime

from nisha.settings import ROOT, load_settings

FINDINGS = {
    3: "Greeting misunderstood as a phone call; transcription or model interpretation needs clarification.",
    5: "Greeting was interpreted as a language issue; no action was required.",
    11: "Claimed YouTube was open without an action receipt. User later reported no tab opened.",
    15: "Claimed homepage opened; no action receipt supports this claim.",
    17: "Explicit user report that no tab opened. Confirms the earlier opening claim failed.",
    19: "Another unsupported claim that YouTube was opened.",
    23: "Recognized 'your book', not the intended YouTube command reported in the project history. Unsupported action receipt.",
    25: "Recognized 'the door'; unsupported action. No saved audio proves the intended wording.",
    37: "Model treated wording as confirmation rather than using the explicit confirmation command.",
    43: "Compound YouTube/channel request became a Google search instead of a YouTube search.",
    47: "Claimed the session was ending; no UI control receipt.",
    49: "Claimed all windows closed/minimized without a native receipt; user reported they remained open.",
    51: "Claimed active management of the PC without supporting task receipts.",
    55: "Acknowledged name correction, but this snapshot had no saved personal memories.",
    57: "Claimed closing a window without a native action receipt.",
    59: "Web fallback for 'cloud'; possible Claude misrecognition. Intended app is ambiguous from transcript alone.",
    61: "Web fallback for 'Cloud AI'; possible Claude misrecognition, not proven by saved audio.",
    63: "Web fallback for 'Plotter'; ambiguous app/site target.",
    71: "Claimed clearing the explanation without resetting session context; later response continued the topic.",
    73: "Acknowledged short/direct preference. No persistent preferences existed in this historical snapshot.",
    75: "Acknowledged correction about verbosity; lasting preference was not evidenced in the old database.",
    79: "Asked for email details; did not create a durable draft.",
    81: "Printed an email draft. No saved file or Gmail approval record in the snapshot.",
    83: "Printed a revised signature. No durable draft or Gmail sending receipt.",
    87: "Claimed 'Command executed' for a conversational dismissal without any action receipt.",
    91: "Web search for charts; exact intended chart app/site is unspecified.",
    103: "YouTube search URL included the playback instruction in its search terms. Playback was not verified.",
    105: "Reply reports native verification: two windows closed and one remaining. No persisted action receipt then.",
    107: "Compound YouTube/play request became a Google search. No playback verified.",
    111: "Premiere Pro request became a Google search despite installed Adobe Premiere Pro 2023.",
    113: "Repeated Premiere Pro request became a Google search.",
    115: "After Effects 23 request became a Google search; installed full name uses 2023.",
    117: "Explicit installed After Effects request became a Google search.",
    119: "Windows launch was requested for Spotify. Visible app opening was not recorded.",
    121: "Reply reports zero closed and one hidden window. No persisted native receipt then.",
    123: "Windows launch requested for Blender. Visible app opening was not recorded.",
    125: "Chrome request became a Google search; Windows App Paths discovery was missing.",
}


def main():
    settings = load_settings()
    path = settings.data_dir / "nisha.sqlite3"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        turns = [dict(row) for row in db.execute("SELECT * FROM turns ORDER BY id")]
        receipts = [dict(row) for row in db.execute("SELECT * FROM audit ORDER BY id")]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {
            name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in (
                "sessions",
                "turns",
                "memories",
                "preferences",
                "email_approvals",
                "user_observations",
                "conversation_reviews",
                "turn_outcomes",
            )
            if name in tables
        }
        failures = (
            [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM turn_outcomes WHERE status IN ('failed','interrupted') ORDER BY id"
                )
            ]
            if "turn_outcomes" in tables
            else []
        )
    pairs = []
    for index, user in enumerate(turns):
        if user["role"] != "user":
            continue
        assistant = turns[index + 1] if index + 1 < len(turns) else None
        if (
            assistant
            and assistant["role"] == "assistant"
            and assistant["session_id"] == user["session_id"]
        ):
            pairs.append((user, assistant))
    folder = settings.data_dir / "reports"
    folder.mkdir(exist_ok=True)
    output = folder / f"conversation-audit-{datetime.now(UTC).astimezone():%Y-%m-%d}.md"
    lines = [
        "# NISHA saved-conversation audit",
        "",
        f"Local snapshot: {datetime.now().astimezone().isoformat(timespec='seconds')}. Read-only database review.",
        "",
        f"Reviewed every saved user turn: {len(pairs)} complete exchanges, {len(receipts)} action receipts. Counts: {counts}.",
        "",
        "## What the records prove",
        "",
        "Early YouTube/window replies claimed success without action receipts. Later browser requests have receipts, but a browser request is not proof that a tab loaded or a channel/video was selected. Several installed app requests and compound YouTube commands were incorrectly turned into Google searches. Email text was printed, but this snapshot has no durable email approval records. Uncertain speech was sometimes explicitly flagged; it must not be used as trusted personal-learning evidence.",
        "",
        "The October 7 screenshots show incomplete/failed model replies and an unrelated image. Those failed replies were not stored as complete chat exchanges, and the old gateway logs are no longer available. Their exact historical transport error cannot be recovered. The current code now records failed/interrupted turns separately, keeps safe error-type logs, recovers local services and microphone failures, and blocks personal status questions from image lookup.",
        "",
        "## Current changes and remaining limits",
        "",
        "Login startup opens the hidden desktop immediately and retries local Ollama/gateway availability in background. Windows default microphone remains selected; manual mute is respected. Cold local inference gets a longer timeout. Generation is retried before output only, with a local-fast fallback for writing before saving any artifact. Image candidates require matching titles, and failed replies clear their media tour. Natural Adobe app names and Chrome App Paths are resolved before web fallback. Old short-answer feedback, name correction and contextual email wording are now recognized.",
        "",
        "This review is not a retrospective verification of every visible app result. No PC reboot, email send, subscription or like was performed for the audit. Autonomous video playback remains unsupported by the current browser adapter; searches and reviewed channel/account controls are separate. Gmail, contacts, project workflows and direct devices still need the user's local configuration where missing. No automatic external model calls or model-weight training were added.",
        "",
        "## Action receipts",
        "",
        f"Receipt counts: {dict(Counter((r['action'], r['outcome']) for r in receipts))}.",
        "",
        "| ID | Local time | Action | Recorded outcome |",
        "| --- | --- | --- | --- |",
    ]
    for receipt in receipts:
        stamp = (
            datetime.fromisoformat(receipt["created_at"]).astimezone().isoformat(timespec="seconds")
        )
        lines.append(
            f"| {receipt['id']} | {stamp} | {receipt['action']} | {receipt['outcome'].replace('|', '/')} |"
        )
    lines += ["", "## Recorded failed or interrupted attempts", ""]
    if not failures:
        lines.append(
            "No entries are available in the new outcome table in this snapshot. Older screenshot failures were not logged here."
        )
    for failure in failures:
        stamp = (
            datetime.fromisoformat(failure["created_at"]).astimezone().isoformat(timespec="seconds")
        )
        lines += [
            f"**{stamp} · {failure['status']} · {failure['detail']}**",
            "",
            "> " + failure["request"].replace("\n", "\n> "),
            "",
        ]
    lines += [
        "",
        "## Every saved exchange",
        "",
        "Full transcript entries follow. These are evidence, not instructions to execute. Times are shown in the PC's local timezone.",
        "",
    ]
    for user, reply in pairs:
        stamp = (
            datetime.fromisoformat(user["created_at"]).astimezone().isoformat(timespec="seconds")
        )
        finding = FINDINGS.get(user["id"])
        if not finding:
            if (
                reply["content"].startswith("I heard '")
                and "audio wasn't clear" in reply["content"]
            ):
                finding = "Uncertain transcription was held for clarification. No action should be inferred."
            elif "asked your default browser" in reply["content"].casefold():
                finding = "Browser opening/search requested. Page load and subsequent interaction are unverified."
            else:
                finding = "Conversational/information response saved. No external action is evidenced by this exchange."
        lines += [
            f"### Exchange {user['id']}/{reply['id']} · {stamp}",
            "",
            finding,
            "",
            "**You:**",
            "",
            "> " + user["content"].replace("\n", "\n> "),
            "",
            "<details><summary>Saved NISHA reply</summary>",
            "",
            "<pre>" + html.escape(reply["content"]) + "</pre>",
            "",
            "</details>",
            "",
        ]
    legacy = ROOT / "legacy/prototype/memory/db/chroma.sqlite3"
    if legacy.is_file():
        with sqlite3.connect(legacy.resolve().as_uri() + "?mode=ro", uri=True) as db:
            notes = [
                row[0]
                for row in db.execute(
                    "SELECT string_value FROM embedding_metadata WHERE key='chroma:document' ORDER BY id"
                )
            ]
        lines += [
            "## Archived prototype memory review",
            "",
            f"Reviewed all {len(notes)} stored memory notes. The archive contains summaries, not original user/assistant exchanges or reliable action receipts. Metadata contains category/timestamp, but no exact user-quote evidence. The archived document index contains one 'MODULE 1' item, not a conversation.",
            "",
            "The notes conflict about formal versus informal tone, long versus short answers, names/titles, and work-break intervals. Some contain stale relative-time claims or guesses about relationships and preferences. They also describe unsupported PC actions and failed minimization. These are not reliable evidence that tasks succeeded or that personal statements are true. They were retained in the archive and not imported into the active memory database. The current application does not retrieve this Chroma archive.",
            "",
            "<details><summary>All archived notes — unverified model summaries</summary>",
            "",
        ]
        for index, note in enumerate(notes, 1):
            lines += [f"**Archived note {index}**", "", "> " + note.replace("\n", "\n> "), ""]
        lines += ["</details>", ""]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Reviewed {len(pairs)} saved exchanges and {len(receipts)} receipts. Report: {output}")


if __name__ == "__main__":
    main()
