"""Gmail sending with an app password kept in Windows Credential Manager."""

import imaplib
import json
import re
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses

from nisha.errors import NishaError


class GmailTransport:
    def __init__(self, data_dir, smtp_factory=None, imap_factory=None):
        self.account_file = data_dir / "gmail-account.json"
        self.smtp_factory = smtp_factory or smtplib.SMTP_SSL
        self.imap_factory = imap_factory or imaplib.IMAP4_SSL

    def configure(self, address, app_password):
        import win32cred

        address = address.strip()
        password = app_password.replace(" ", "")
        if (
            not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address)
            or len(password) != 16
            or not password.isascii()
            or not password.isalnum()
        ):
            raise NishaError("Enter your Gmail address and its 16-character Google app password.")
        try:
            win32cred.CredWrite(
                {
                    "Type": win32cred.CRED_TYPE_GENERIC,
                    "TargetName": "NISHA/Gmail/" + address,
                    "UserName": address,
                    "CredentialBlob": password,
                    "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                },
                0,
            )
            self.account_file.parent.mkdir(parents=True, exist_ok=True)
            self.account_file.write_text(json.dumps({"address": address}), encoding="utf-8")
        except Exception as exc:
            raise NishaError(
                "Gmail setup couldn't be saved. Check Windows Credential Manager and try again."
            ) from exc

    def credentials(self):
        try:
            import win32cred

            address = json.loads(self.account_file.read_text(encoding="utf-8"))["address"]
            record = win32cred.CredRead("NISHA/Gmail/" + address, win32cred.CRED_TYPE_GENERIC)
            password = record["CredentialBlob"]
            if isinstance(password, bytes):
                password = password.decode("utf-16-le")
            return address, password
        except Exception as exc:
            raise NishaError(
                "Gmail isn't connected. Use 'setup gmail' or Ctrl+G in NISHA; your normal Google password won't work."
            ) from exc

    def recent_messages(self, limit=5, since_today=False):
        """User-requested inbox fetch; readonly/PEEK leaves messages and flags untouched."""
        address, password = self.credentials()
        try:
            with self.imap_factory(
                "imap.gmail.com", 993, timeout=20, ssl_context=ssl.create_default_context()
            ) as inbox:
                inbox.login(address, password)
                status, _ = inbox.select("INBOX", readonly=True)
                if status != "OK":
                    raise NishaError("Gmail couldn't open the inbox in read-only mode.")
                if since_today:
                    from datetime import datetime

                    since = datetime.now().astimezone().strftime("%d-%b-%Y")
                    status, data = inbox.uid("search", None, "SINCE", since)
                else:
                    status, data = inbox.uid("search", None, "ALL")
                if status != "OK":
                    raise NishaError("Gmail couldn't list inbox messages.")
                messages = []
                for uid in reversed(data[0].split()[-min(limit, 10) :]):
                    # Fetch at most 100KB; attachments and remote HTML content are never opened.
                    status, data = inbox.uid("fetch", uid, "(BODY.PEEK[]<0.100000>)")
                    raw = next((part[1] for part in data if isinstance(part, tuple)), None)
                    if status != "OK" or not raw:
                        continue
                    message = BytesParser(policy=policy.default).parsebytes(raw)
                    recipients = getaddresses(
                        message.get_all("Reply-To", []) or message.get_all("From", [])
                    )
                    recipient = recipients[0][1] if len(recipients) == 1 else ""
                    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
                        recipient = ""
                    body = message.get_body(preferencelist=("plain",))
                    content = (
                        body.get_content()
                        if body
                        else "[No plain-text body; review this message in Gmail.]"
                    )
                    references = " ".join(
                        re.findall(r"<[^<>\s]{1,200}>", str(message.get("References", "")))
                    )[:1800]
                    message_id = str(message.get("Message-ID", ""))
                    message_id = message_id if re.fullmatch(r"<[^<>\s]{1,200}>", message_id) else ""
                    messages.append(
                        {
                            "uid": uid.decode("ascii"),
                            "sender": str(message.get("From", ""))[:300],
                            "recipient": recipient,
                            "subject": str(message.get("Subject", ""))[:300]
                            .replace("\r", " ")
                            .replace("\n", " "),
                            "body": str(content)[:12000],
                            "message_id": message_id,
                            "references": references,
                        }
                    )
                return messages
        except (imaplib.IMAP4.error, OSError, ValueError) as exc:
            raise NishaError(
                "Gmail inbox access failed. Check the app password and your account's IMAP policy."
            ) from exc

    def send_email(self, recipient, subject, body, reply_headers=None):
        address, password = self.credentials()
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = address, recipient, subject
        for key, value in (reply_headers or {}).items():
            if key not in {"In-Reply-To", "References"} or "\r" in value or "\n" in value:
                raise NishaError("The reply threading headers are invalid. Create a fresh draft.")
            if value:
                message[key] = value
        message.set_content(body)
        try:
            with self.smtp_factory(
                "smtp.gmail.com", 465, timeout=30, context=ssl.create_default_context()
            ) as smtp:
                smtp.login(address, password)
                refused = smtp.send_message(message)
                if refused:
                    raise NishaError("Gmail rejected the recipient. Nothing was confirmed as sent.")
            return "Gmail accepted the approved email for delivery."
        except smtplib.SMTPAuthenticationError as exc:
            raise NishaError(
                "Gmail sign-in failed. Check or replace the Google app password in setup."
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise NishaError(
                "Gmail submission couldn't be confirmed. Check your Sent folder before sending again."
            ) from exc
