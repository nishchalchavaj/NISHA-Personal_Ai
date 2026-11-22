"""Round-trip a unique synthetic credential, then delete it; no Gmail connection."""

from tempfile import TemporaryDirectory
from uuid import uuid4

import win32cred

from nisha.mail import GmailTransport
from nisha.settings import load_settings


def main():
    settings = load_settings()
    address = f"nisha-test-{uuid4().hex}@example.invalid"
    target = "NISHA/Gmail/" + address
    with TemporaryDirectory(prefix="credential-test-", dir=settings.data_dir) as directory:
        from pathlib import Path

        mailer = GmailTransport(Path(directory))
        try:
            mailer.configure(address, "abcdefghijklmnop")
            assert mailer.credentials() == (address, "abcdefghijklmnop")
            assert "abcdefghijklmnop" not in mailer.account_file.read_text()
        finally:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC)
    print(
        "PASS: Windows Credential Manager write/read; synthetic credential removed. No email sent."
    )


if __name__ == "__main__":
    main()
