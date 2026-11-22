"""Optional external task workers; no conversation or memory is attached."""

import json
import re
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from uuid import uuid4

import httpx

from nisha.errors import NishaError, PrivacyError

PROVIDERS = {
    "OpenAI": "https://api.openai.com/v1/responses",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/models/",
    "Claude": "https://api.anthropic.com/v1/messages",
}


@dataclass(frozen=True)
class TaskApproval:
    token: str
    provider: str
    model: str
    text: str
    learn: bool
    expires: float


class ExternalWorkers:
    def __init__(self, data_dir, client=None, key_reader=None, enabled=True):
        self.profile = data_dir / "worker-settings.json"
        self.client = client
        self.key_reader = key_reader or self.read_key
        self.pending = {}
        self.lock = RLock()
        self.enabled = enabled

    def settings(self):
        try:
            settings = json.loads(self.profile.read_text(encoding="utf-8"))
            if (
                not isinstance(settings, dict)
                or not isinstance(settings.get("provider"), str)
                or settings.get("provider") not in PROVIDERS
                or not isinstance(settings.get("model"), str)
                or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,100}", settings["model"])
            ):
                return {}
            return {"provider": settings["provider"], "model": settings["model"]}
        except (OSError, ValueError):
            return {}

    def configure(self, provider, model, api_key):
        import win32cred

        if (
            provider not in PROVIDERS
            or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,100}", model)
            or not api_key.strip()
        ):
            raise NishaError("Select a provider and enter a valid API model name and key.")
        try:
            win32cred.CredWrite(
                {
                    "Type": win32cred.CRED_TYPE_GENERIC,
                    "TargetName": "NISHA/Worker/" + provider,
                    "UserName": provider,
                    "CredentialBlob": api_key.strip(),
                    "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                },
                0,
            )
            self.profile.write_text(
                json.dumps({"provider": provider, "model": model}), encoding="utf-8"
            )
        except Exception as exc:
            raise NishaError(
                "The worker connection couldn't be saved in Windows Credential Manager."
            ) from exc

    @staticmethod
    def read_key(provider):
        try:
            import win32cred

            key = win32cred.CredRead("NISHA/Worker/" + provider, win32cred.CRED_TYPE_GENERIC)[
                "CredentialBlob"
            ]
            return key.decode("utf-16-le") if isinstance(key, bytes) else key
        except Exception as exc:
            raise NishaError(
                "Connect this task provider first using Ctrl+K. Keep API keys out of chat."
            ) from exc

    def propose(self, provider, model, text, learn=True):
        if (
            provider not in PROVIDERS
            or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,100}", model)
            or not 1 <= len(text.strip()) <= 20_000
        ):
            raise NishaError(
                "Enter a standalone task up to 20,000 characters and a valid provider/model."
            )
        approval = TaskApproval(
            uuid4().hex, provider, model, text.strip(), learn, monotonic() + 300
        )
        with self.lock:
            self.pending = {approval.token: approval}
        return approval

    def cancel(self, token):
        with self.lock:
            self.pending.pop(token, None)

    def run(self, approval, approved=False):
        if not self.enabled:
            raise PrivacyError(
                "External task workers are disabled in this local-only installation."
            )
        if not approved:
            raise PrivacyError("Approve the exact standalone task before sending it externally.")
        with self.lock:
            saved = self.pending.pop(approval.token, None)
        if saved != approval or approval.expires < monotonic():
            raise PrivacyError(
                "This task approval changed, expired or was already used. Review it again."
            )
        key = self.key_reader(approval.provider)
        if self.client:
            return self.request(approval, key, self.client)
        with httpx.Client(timeout=90, trust_env=False) as client:
            return self.request(approval, key, client)

    @staticmethod
    def request(task, key, client):
        url = PROVIDERS[task.provider]
        if task.provider == "OpenAI":
            headers = {"Authorization": "Bearer " + key}
            payload = {
                "model": task.model,
                "input": task.text,
                "store": False,
                "max_output_tokens": 2048,
            }
        elif task.provider == "Gemini":
            url += task.model + ":generateContent"
            headers = {"x-goog-api-key": key}
            payload = {
                "contents": [{"role": "user", "parts": [{"text": task.text}]}],
                "generationConfig": {"maxOutputTokens": 2048},
            }
        else:
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            payload = {
                "model": task.model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": task.text}],
            }
        try:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("Invalid task provider response")
            if task.provider == "OpenAI":
                if data.get("status") not in {None, "completed"}:
                    raise NishaError(
                        "The external task didn't complete. Its result wasn't learned."
                    )
                result = "\n".join(
                    part["text"]
                    for item in data.get("output", [])
                    if item.get("type") == "message"
                    for part in item.get("content", [])
                    if part.get("type") == "output_text"
                )
            elif task.provider == "Gemini":
                candidate = data.get("candidates", [{}])[0]
                if candidate.get("finishReason") not in {None, "STOP"}:
                    raise NishaError(
                        "The external task didn't complete. Its result wasn't learned."
                    )
                result = "\n".join(
                    part["text"]
                    for part in candidate.get("content", {}).get("parts", [])
                    if "text" in part
                )
            else:
                if data.get("stop_reason") not in {None, "end_turn", "stop_sequence"}:
                    raise NishaError(
                        "The external task didn't complete. Its result wasn't learned."
                    )
                result = "\n".join(
                    part["text"] for part in data.get("content", []) if part.get("type") == "text"
                )
            if not result.strip():
                raise NishaError("The task provider returned no usable text.")
            return result
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            raise NishaError(
                "The external task failed. Check the provider connection, API model name and account balance. No automatic retry was made."
            ) from exc
