import pytest

from nisha.errors import NishaError
from nisha.mail import GmailTransport


def test_gmail_uses_tls_and_exact_approved_payload_without_exposing_credentials(tmp_path):
    captured = []

    class SMTP:
        def __init__(self, host, port, timeout, context):
            assert host == "smtp.gmail.com" and port == 465
            assert context.check_hostname

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, address, password):
            assert address == "sender@gmail.com" and password == "synthetic-test-password"

        def send_message(self, message):
            captured.append(message)
            return {}

    mailer = GmailTransport(tmp_path, SMTP)
    mailer.credentials = lambda: ("sender@gmail.com", "synthetic-test-password")
    result = mailer.send_email("alex@example.com", "Approved subject", "Approved body")
    assert "accepted" in result
    assert captured[0]["To"] == "alex@example.com"
    assert captured[0].get_content().strip() == "Approved body"


def test_missing_gmail_account_does_not_attempt_network(tmp_path):
    mailer = GmailTransport(tmp_path, lambda *args, **kwargs: pytest.fail("Unexpected network"))
    with pytest.raises(NishaError, match="Gmail isn't connected"):
        mailer.send_email("alex@example.com", "subject", "body")


def test_normal_google_password_rejected_before_credential_write(tmp_path):
    with pytest.raises(NishaError, match="16-character"):
        GmailTransport(tmp_path).configure("sender@gmail.com", "normal-password")
