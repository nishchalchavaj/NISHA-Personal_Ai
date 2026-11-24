import ast
import json
from time import time

import pytest

from nisha.errors import NishaError
from nisha.workflows import WorkflowService


class Desktop:
    def __init__(self):
        self.opened = []

    def app_path(self, name):
        return "notepad.exe" if name == "notepad" else None

    def open_app(self, name):
        self.opened.append(name)

    def open_document(self, path, app):
        self.opened.append((path, app))


class Mailer:
    def __init__(self):
        self.sent = []
        self.messages = []
        self.fetch_options = []

    def recent_messages(self, **options):
        self.fetch_options.append(options)
        return self.messages

    def send_email(self, recipient, subject, body):
        self.sent.append((recipient, subject, body))
        return "Gmail accepted the approved email for delivery."


@pytest.fixture
def workflows(core):
    desktop, mailer = Desktop(), Mailer()
    core.workflows = WorkflowService(core.settings, desktop, mailer)
    return core, desktop, mailer


def test_notepad_generation_saves_real_content_without_overwriting(workflows):
    core, desktop, _ = workflows
    core.generate_content = lambda *args: "Solar panels turn sunlight into electricity."
    session = core.new_session()
    reply = core.chat("Write about solar power in Notepad", session)
    path, app = desktop.opened[-1]
    assert app == "notepad" and path.read_text() == "Solar panels turn sunlight into electricity."
    assert "Saved" in reply and "Solar" in reply
    core.chat("Write another note about solar power", session)
    assert desktop.opened[-1][0] != path


@pytest.mark.parametrize(
    "text",
    [
        "It's okay, write an email.",
        "Leave the sender and recipient. Just write an email about delayed items of electronic components and keep it in draft.",
    ],
)
def test_historical_contextual_email_requests_create_actual_pending_drafts(workflows, text):
    core, desktop, mailer = workflows
    core.generate_content = lambda *args: json.dumps(
        {"subject": "Urgent components", "body": "Please deliver the components urgently."}
    )
    session = core.new_session()
    response = core.chat(text, session)
    pending = core.store.pending_email(session)
    assert pending and "nothing sent" in response and not mailer.sent and not desktop.opened
    assert (core.workflows.workspace / f"email-{pending['token']}.json").is_file()


def test_batch_replies_make_local_review_file_for_each_today_message(workflows):
    core, _, mailer = workflows
    mailer.messages = [
        {
            "sender": "A <a@example.test>", "recipient": "a@example.test",
            "subject": "Class notes", "body": "Can you share the notes?",
            "message_id": "<a@example.test>", "references": "",
        },
        {
            "sender": "B <b@example.test>", "recipient": "b@example.test",
            "subject": "Meeting", "body": "Are you available tomorrow?",
            "message_id": "<b@example.test>", "references": "",
        },
    ]
    core.generate_content = lambda *args: json.dumps(
        {"subject": "Reply", "body": "Thanks, I will check and get back to you."}
    )
    session = core.new_session()
    result = core.chat("check all new email and write draft reply for all", session)
    assert "Prepared 2 local reply draft(s)" in result
    assert "nothing was sent" in result
    assert mailer.fetch_options == [{"unread_only": True, "limit": 10}]
    assert not mailer.sent and not core.store.pending_email(session)
    batch = next(core.workflows.workspace.glob("email-replies-*.json"))
    drafts = json.loads(batch.read_text(encoding="utf-8"))
    assert [item["recipient"] for item in drafts] == ["a@example.test", "b@example.test"]
    assert all(item["subject"].startswith("Re:") for item in drafts)


def test_local_smart_outage_falls_back_before_saving_and_opening_one_artifact(workflows):
    from nisha.errors import ModelUnavailable
    from nisha.settings import ModelProfile

    core, desktop, _ = workflows
    core.settings.models["local_smart"] = ModelProfile(
        model="ollama_chat/qwen3:14b", local=True, context_window=4096, max_output=256
    )
    calls = []

    def generate(alias, messages, **kwargs):
        calls.append(alias)
        if alias == "local_smart":
            raise ModelUnavailable("Local writing model stopped")
        return "Recovered local writing."

    core.gateway.generate = generate
    response = core.chat("Write about solar power in Notepad", core.new_session())
    assert calls == ["local_smart", "local_fast"]
    assert len(desktop.opened) == 1 and "Saved" in response
    assert len(list(core.workflows.workspace.glob("*.txt"))) == 1


def test_historical_email_signature_correction_revises_pending_draft(workflows):
    core, desktop, mailer = workflows
    session = core.new_session()
    core.interaction.observe("My name is not Nishal, it's Nishchal.")
    core.generate_content = lambda *args: json.dumps(
        {"subject": "Urgent components", "body": "Please deliver urgently.\n[Your name]"}
    )
    core.chat("Write an email about delayed components", session)
    old = core.store.pending_email(session)["token"]
    calls = []

    def revise(text, session, alias, instructions, schema):
        calls.append(schema)
        return json.dumps(
            {"subject": "Urgent components", "body": "Please deliver urgently.\nNishchal"}
        )

    core.generate_content = revise
    response = core.chat("In place of your name, add my name. You know my name.", session)
    pending = core.store.pending_email(session)
    draft = json.loads((core.workflows.workspace / f"email-{pending['token']}.json").read_text())
    assert pending["token"] != old and calls and "Nishchal" in draft["body"]
    assert "nothing sent" in response and not mailer.sent and not desktop.opened


def test_file_follow_up_opens_the_previous_document(workflows):
    core, desktop, _ = workflows
    core.generate_content = lambda *args: "Local note"
    session = core.new_session()
    core.chat("Write a note in Notepad", session)
    previous = desktop.opened[-1]
    reply = core.chat("open it", session)
    assert desktop.opened[-1] == previous
    assert "Opened the earlier file" in reply


def test_word_document_contains_generated_content(workflows):
    from docx import Document

    core, desktop, _ = workflows
    core.generate_content = lambda *args: "Study plan\nPractice Python daily."
    core.chat("Write a study plan in Word", core.new_session())
    path, app = desktop.opened[-1]
    assert app == "word" and path.suffix == ".docx"
    assert "Practice Python" in "\n".join(p.text for p in Document(path).paragraphs)


def test_code_saved_as_source_in_editor_and_never_executed(workflows):
    core, desktop, _ = workflows
    core.generate_content = lambda *args: "```python\ndef add(a, b):\n    return a + b\n```"
    core.chat("Write Python code to add numbers", core.new_session())
    path, app = desktop.opened[-1]
    assert path.suffix == ".py" and app == "vscode"
    ast.parse(path.read_text())
    assert "```" not in path.read_text()


def test_code_revision_preserves_language_without_repeating_it(workflows):
    core, desktop, _ = workflows
    core.generate_content = lambda *args: "function add(a, b) { return a + b; }"
    session = core.new_session()
    core.chat("Write JavaScript code to add two numbers", session)
    original, _ = desktop.opened[-1]
    core.chat("make it shorter", session)
    revised, app = desktop.opened[-1]
    assert revised.suffix == ".js" and app == "vscode" and revised != original


def test_email_draft_requires_exact_approval_then_sends_once(workflows):
    core, _, mailer = workflows
    core.generate_content = lambda *args: json.dumps(
        {"subject": "Meeting", "body": "Can we meet tomorrow?"}
    )
    session = core.new_session()
    assert "nothing sent" in core.chat(
        "Write an email to alex@example.com about a meeting", session
    )
    pending = core.store.pending_email(session)
    assert not mailer.sent
    assert "eight-character" in core.chat("yes", session)
    assert not mailer.sent
    reply = core.chat("approve email " + pending["token"], session)
    assert "Gmail accepted" in reply
    assert mailer.sent == [("alex@example.com", "Meeting", "Can we meet tomorrow?")]
    assert "already used" in core.chat("approve email " + pending["token"], session)
    assert len(mailer.sent) == 1


@pytest.mark.parametrize("change", ["edit", "cancel", "expire", "wrong_session", "supersede"])
def test_invalid_draft_approval_never_sends(workflows, change):
    core, _, mailer = workflows
    session = core.new_session()
    core.workflows.draft_email(session, "alex@example.com", "Hello", "Original", core.store)
    pending = core.store.pending_email(session)
    if change == "edit":
        from pathlib import Path

        Path(pending["path"]).write_text("{}", encoding="utf-8")
    elif change == "cancel":
        core.store.cancel_email(session)
    elif change == "expire":
        with core.store.connect() as db:
            db.execute("UPDATE email_approvals SET expires=?", (time() - 1,))
    elif change == "wrong_session":
        session = core.new_session()
    else:
        core.workflows.draft_email(session, "bob@example.com", "New", "Changed", core.store)
    core.chat("approve email " + pending["token"], session)
    assert not mailer.sent


def test_missing_recipient_and_malformed_email_never_send(workflows):
    core, _, mailer = workflows
    core.generate_content = lambda *args: '{"subject":"Hello","body":"Good morning"}'
    session = core.new_session()
    reply = core.chat("Write an email about a meeting", session)
    assert "exact recipient address" in reply
    pending = core.store.pending_email(session)
    core.chat("approve email " + pending["token"], session)
    assert not mailer.sent


def test_spoken_recipient_follow_up_and_revision_require_new_approval(workflows):
    core, _, mailer = workflows
    core.generate_content = lambda *args: '{"subject":"Hello","body":"Good morning"}'
    session = core.new_session()
    core.chat("Write an email about a meeting", session)
    original = core.store.pending_email(session)
    core.chat("send it to alex at gmail dot com", session)
    addressed = core.store.pending_email(session)
    assert addressed["token"] != original["token"] and not mailer.sent
    payload = json.loads(
        (core.workflows.workspace / f"email-{addressed['token']}.json").read_text()
    )
    assert payload["recipient"] == "alex@gmail.com"
    core.chat("make it shorter", session)
    revised = core.store.pending_email(session)
    assert revised["token"] != addressed["token"]
    core.chat("approve email " + addressed["token"], session)
    assert not mailer.sent
    core.chat("approve email " + revised["token"], session)
    assert mailer.sent[0][0] == "alex@gmail.com"
    before = len(mailer.sent)
    core.generate_content = lambda *args: "not valid JSON"
    assert "Nothing was sent" in core.chat("Write email to alex@example.com", session)
    assert len(mailer.sent) == before


def test_low_confidence_speech_cannot_execute_until_confirmed(core):
    from nisha.actions import WebsiteActions

    calls = []
    core.actions = WebsiteActions(lambda url, new: calls.append(url) or True)
    session = core.new_session()
    reply = "".join(core.stream("open youtube", session, uncertain=True))
    assert "audio wasn't clear" in reply and not calls
    core.chat("confirm command", session)
    assert calls == ["https://www.youtube.com/"]


def test_failure_to_open_editor_keeps_saved_file_and_truthful_receipt(workflows):
    core, desktop, _ = workflows
    core.generate_content = lambda *args: "Local content"

    def fail(*args):
        raise NishaError("Editor unavailable")

    desktop.open_document = fail
    reply = core.chat("Write a note in Notepad", core.new_session())
    assert "Editor unavailable" in reply
    assert next(core.workflows.workspace.glob("*.txt")).read_text() == "Local content"


@pytest.mark.parametrize(
    "utterance",
    [
        "I am the customer and the components have not arrived yet. So write them email asking for urgent delivery.",
        "I haven't received the components so write the supplier's email about urgent delivery.",
        "The supplier is late. Please draft an email requesting a delivery date.",
    ],
)
def test_context_before_email_request_still_creates_complete_reviewable_draft(workflows, utterance):
    core, desktop, mailer = workflows
    received = []
    body = (
        "Our components are overdue. Please dispatch them urgently and confirm the delivery date."
    )

    def generate(topic, *args):
        received.append(topic)
        return json.dumps({"subject": "Urgent overdue components", "body": body})

    core.generate_content = generate
    session = core.new_session()
    reply = core.chat(utterance, session)
    assert received == [utterance] and "nothing sent" in reply
    pending = core.store.pending_email(session)
    draft = json.loads((core.workflows.workspace / f"email-{pending['token']}.json").read_text())
    assert draft["body"] == body and not mailer.sent and not desktop.opened


@pytest.mark.parametrize(
    "utterance",
    [
        'Explain the sentence "So write them email asking for urgent delivery".',
        "Why does the phrase so write them email sound wrong?",
    ],
)
def test_discussing_writing_words_does_not_create_a_draft(workflows, utterance):
    core, desktop, mailer = workflows
    session = core.new_session()
    core.chat(utterance, session)
    assert not core.store.pending_email(session) and not mailer.sent and not desktop.opened
