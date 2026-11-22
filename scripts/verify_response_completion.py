"""Real local continuation and contextual email drafting; no email is sent."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from nisha.core import NishaCore
from nisha.gateway import Gateway
from nisha.settings import load_settings


def main():
    settings = load_settings()
    completions = []

    def record(request):
        if request.url.path.endswith("/chat/completions"):
            completions.append(json.loads(request.content)["max_tokens"])

    with httpx.Client(
        timeout=httpx.Timeout(settings.request_timeout, connect=5),
        trust_env=False,
        event_hooks={"request": [record]},
    ) as client:
        gateway = Gateway(settings, client)
        messages = [
            {
                "role": "system",
                "content": "Explain clearly. Complete the requested explanation; do not add offers or questions.",
            },
            {
                "role": "user",
                "content": "Explain how photosynthesis works, covering sunlight, chlorophyll, water, carbon dioxide, glucose and oxygen. Use three short paragraphs, around 150 words.",
            },
        ]
        reply = "".join(gateway.continued("local_fast", messages, output_tokens=64))
        assert len(completions) >= 2, (
            "The forced small output budget did not exercise continuation."
        )
        assert all(
            term in reply.casefold()
            for term in ["chlorophyll", "water", "carbon dioxide", "glucose", "oxygen"]
        ), reply
        assert reply.rstrip().endswith((".", "!", "?")), reply
        print(
            f"PASS: actual local answer completed over {len(completions)} forced 64-token segments ({len(reply.split())} words).",
            flush=True,
        )
        with TemporaryDirectory(prefix="response-test-", dir=settings.data_dir) as directory:
            core = NishaCore(
                settings.model_copy(update={"data_dir": Path(directory)}), gateway=gateway
            )
            session = core.new_session()
            request = "I am the customer who is in trouble because the components have not arrived yet. So write them email asking for fast delivery on time. I need them urgently."
            response = core.chat(request, session)
            pending = core.store.pending_email(session)
            assert pending and "nothing sent" in response, response
            draft = json.loads(
                (core.workflows.workspace / f"email-{pending['token']}.json").read_text(
                    encoding="utf-8"
                )
            )
            assert draft["subject"] and len(draft["body"].split()) >= 30, draft
            print(
                f"PASS: contextual request produced a complete local JSON email draft ({len(draft['body'].split())} body words), awaiting recipient/review. No sending approval or mail transport was invoked.",
                flush=True,
            )


if __name__ == "__main__":
    main()
