import json
from email.message import EmailMessage

import pytest

from nisha.errors import NishaError
from nisha.mail import GmailTransport


class Inbox:
    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def login(self, address, password):
        self.calls.append(("login", address))

    def select(self, name, readonly):
        self.calls.append(("select", name, readonly))
        return "OK", [b"1"]

    def uid(self, operation, *args):
        self.calls.append((operation, *args))
        return ("OK", [b"42"]) if operation == "search" else ("OK", [(b"data", self.raw), b")"])


def email_bytes(reply_to="alex@example.org"):
    message = EmailMessage()
    message["From"] = "Alex <alex@example.org>"
    message["Reply-To"] = reply_to
    message["Subject"] = "Presentation tomorrow"
    message["Message-ID"] = "<message-42@example.org>"
    message["References"] = "<message-40@example.org>"
    message.set_content("Can you send the notes? Do not invent a promise.")
    return message.as_bytes()


def test_inbox_readonly_peek_exact_reply_context(tmp_path):
    inbox, connections = Inbox(email_bytes()), []

    def factory(*args, **kwargs):
        connections.append((args, kwargs))
        return inbox

    mailer = GmailTransport(tmp_path, imap_factory=factory)
    mailer.credentials = lambda: ("owner@gmail.com", "test-password")
    messages = mailer.recent_messages()
    assert messages[0]["recipient"] == "alex@example.org"
    assert messages[0]["message_id"] == "<message-42@example.org>"
    assert ("select", "INBOX", True) in inbox.calls
    assert ("fetch", b"42", "(BODY.PEEK[]<0.100000>)") in inbox.calls
    assert connections[0][0] == ("imap.gmail.com", 993)
    assert connections[0][1]["ssl_context"].check_hostname
    assert not list(tmp_path.iterdir())


def test_unread_check_uses_unseen_search_and_peek_without_marking_read(tmp_path):
    inbox = Inbox(email_bytes())
    mailer = GmailTransport(tmp_path, imap_factory=lambda *args, **kwargs: inbox)
    mailer.credentials = lambda: ("owner@gmail.com", "test-password")
    assert mailer.recent_messages(unread_only=True)[0]["uid"] == "42"
    assert ("search", None, "UNSEEN") in inbox.calls
    assert ("fetch", b"42", "(BODY.PEEK[]<0.100000>)") in inbox.calls


def test_ambiguous_reply_to_does_not_choose_recipient(tmp_path):
    inbox = Inbox(email_bytes("alex@example.org, second@example.org"))
    mailer = GmailTransport(tmp_path, imap_factory=lambda *args, **kwargs: inbox)
    mailer.credentials = lambda: ("owner@gmail.com", "test-password")
    assert mailer.recent_messages()[0]["recipient"] == ""


class SelectedMailer:
    def __init__(self):
        self.sent = []

    def recent_messages(self):
        return [
            {
                "uid": "42",
                "sender": "Alex <alex@example.org>",
                "recipient": "alex@example.org",
                "subject": "Presentation",
                "body": "Can you share notes?",
                "message_id": "<42@example.org>",
                "references": "<40@example.org>",
            }
        ]

    def send_email(self, recipient, subject, body, reply_headers=None):
        self.sent.append((recipient, subject, body, reply_headers))
        return "Gmail accepted the approved email for delivery."


@pytest.fixture
def replies(core):
    mailer = SelectedMailer()
    core.workflows.mailer = mailer
    core.generate_content = lambda *args: json.dumps(
        {
            "subject": "Ignored generated subject",
            "body": "I will review the notes and get back to you.",
        }
    )
    return core, mailer


def test_reply_requires_selected_message_and_exact_send_approval(replies):
    core, mailer = replies
    session = core.new_session()
    assert "Who should I reply" in core.chat("reply to him", session)
    assert "Recent Gmail" in core.chat("check Gmail", session)
    assert "Who should I reply" in core.chat("reply to him", session)
    assert "Selected email 1" in core.chat("select email one", session)
    draft = core.chat("reply to him", session)
    assert "To: alex@example.org" in draft and "Subject: Re: Presentation" in draft
    assert not mailer.sent
    token = core.store.pending_email(session)["token"]
    assert "Approve the exact draft" in core.chat("send it", session)
    assert not mailer.sent
    core.chat("approve email " + token, session)
    assert mailer.sent[0] == (
        "alex@example.org",
        "Re: Presentation",
        "I will review the notes and get back to you.",
        {"In-Reply-To": "<42@example.org>", "References": "<40@example.org> <42@example.org>"},
    )
    core.chat("approve email " + token, session)
    assert len(mailer.sent) == 1


def test_reply_context_session_boundary_and_refresh(replies):
    core, _ = replies
    session = core.new_session()
    core.chat("check gmail", session)
    core.chat("select email 1", session)
    assert "Who should I reply" in core.chat("reply to him", core.new_session())
    core.chat("check gmail", session)
    assert "Who should I reply" in core.chat("reply to him", session)


def test_named_recipient_must_match_selected_email(replies):
    core, _ = replies
    session = core.new_session()
    core.chat("check gmail", session)
    core.chat("select email 1", session)
    assert "someone else" in core.chat("reply to Bob", session)
    assert core.store.pending_email(session) is None
    assert "Email draft" in core.chat("reply to Alex", session)


def test_selected_email_context_expires(replies):
    core, _ = replies
    session = core.new_session()
    core.chat("check gmail", session)
    core.chat("select email 1", session)
    core.workflows.selected_messages[session]["selected_at"] -= 1801
    assert "context expired" in core.chat("reply to him", session)
    assert core.store.pending_email(session) is None


def test_reply_revision_preserves_thread_but_requires_fresh_approval(replies):
    core, mailer = replies
    session = core.new_session()
    core.chat("check gmail", session)
    core.chat("select email 1", session)
    core.chat("reply to him", session)
    old = core.store.pending_email(session)["token"]
    core.chat("rewrite the email in simpler words", session)
    token = core.store.pending_email(session)["token"]
    assert token != old
    assert "expired" in core.chat("approve email " + old, session)
    core.chat("approve email " + token, session)
    assert mailer.sent[0][3]["In-Reply-To"] == "<42@example.org>"


def test_changed_reply_draft_is_never_submitted(replies):
    core, mailer = replies
    session = core.new_session()
    core.chat("check gmail", session)
    core.chat("select email 1", session)
    core.chat("reply to him", session)
    token = core.store.pending_email(session)["token"]
    path = core.workflows.workspace / f"email-{token}.json"
    draft = json.loads(path.read_text())
    draft["reply_headers"]["In-Reply-To"] = "<different@example.org>"
    path.write_text(json.dumps(draft))
    assert "changed after review" in core.chat("approve email " + token, session)
    assert not mailer.sent


def test_no_network_when_gmail_is_unconfigured(tmp_path):
    mailer = GmailTransport(
        tmp_path, imap_factory=lambda *args, **kwargs: pytest.fail("network should not run")
    )
    with pytest.raises(NishaError, match="isn't connected"):
        mailer.recent_messages()
