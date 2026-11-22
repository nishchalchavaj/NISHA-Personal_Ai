import json
from dataclasses import replace

import httpx
import pytest

from nisha.errors import NishaError, PrivacyError
from nisha.workers import ExternalWorkers


@pytest.mark.parametrize(
    "provider,response",
    [
        (
            "OpenAI",
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Synthetic result"}],
                    }
                ],
            },
        ),
        (
            "Gemini",
            {
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "Synthetic result"}]}}
                ]
            },
        ),
        (
            "Claude",
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Synthetic result"}]},
        ),
    ],
)
def test_only_exact_approved_task_sent_no_memory_or_conversation(core, provider, response):
    requests = []
    core.memory.remember("Private medical history")
    core.chat("Private family conversation", core.new_session())

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    workers = ExternalWorkers(
        core.settings.data_dir,
        httpx.Client(transport=httpx.MockTransport(handler)),
        lambda name: "synthetic-key",
    )
    approval = workers.propose(provider, "test-model", "Explain sorting algorithms")
    with pytest.raises(PrivacyError):
        workers.run(approval)
    assert not requests
    assert workers.run(approval, approved=True) == "Synthetic result"
    payload = json.loads(requests[0].content)
    assert "Private" not in str(payload) and "sorting algorithms" in str(payload)
    if provider == "OpenAI":
        assert payload["store"] is False
    with pytest.raises(PrivacyError):
        workers.run(approval, approved=True)
    assert len(requests) == 1


@pytest.mark.parametrize("change", ["mutate", "expire", "cancel", "supersede"])
def test_invalid_task_approvals_never_make_network_request(tmp_path, change):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected external request"))
    )
    workers = ExternalWorkers(tmp_path, client, lambda provider: "synthetic-key")
    approval = workers.propose("OpenAI", "test-model", "Standalone task")
    if change == "mutate":
        approval = replace(approval, text="Changed task")
    elif change == "expire":
        approval = replace(approval, expires=0)
        workers.pending[approval.token] = approval
    elif change == "cancel":
        workers.cancel(approval.token)
    else:
        workers.propose("OpenAI", "test-model", "Different task")
    with pytest.raises(PrivacyError):
        workers.run(approval, approved=True)


def test_failed_external_call_does_not_leak_provider_error_or_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": "synthetic-secret-in-error-body"})

    workers = ExternalWorkers(
        tmp_path, httpx.Client(transport=httpx.MockTransport(handler)), lambda provider: "secret"
    )
    approval = workers.propose("OpenAI", "test-model", "Standalone task")
    with pytest.raises(NishaError) as error:
        workers.run(approval, approved=True)
    assert "synthetic-secret" not in str(error.value) and len(calls) == 1


def test_unknown_provider_and_url_in_model_rejected(tmp_path):
    workers = ExternalWorkers(tmp_path)
    with pytest.raises(NishaError):
        workers.propose("Unknown", "model", "task")
    with pytest.raises(NishaError):
        workers.propose("Gemini", "https://internal/secret", "task")
