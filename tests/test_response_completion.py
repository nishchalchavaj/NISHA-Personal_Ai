import json

import httpx
import pytest

from nisha.context import token_bound
from nisha.errors import ModelUnavailable
from nisha.gateway import Gateway


def gateway_for(settings, responses):
    calls = []

    def handle(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        calls.append(json.loads(request.content))
        text, finish = responses[min(len(calls) - 1, len(responses) - 1)]
        events = [
            json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": finish}]}),
            "[DONE]",
        ]
        return httpx.Response(200, text="".join("data: " + event + "\n\n" for event in events))

    client = httpx.Client(transport=httpx.MockTransport(handle))
    return Gateway(settings, client), calls


def test_length_stop_continues_final_delta_and_stores_only_completed_reply(core):
    gateway, calls = gateway_for(
        core.settings,
        [("The delivery is", "length"), (" overdue. Please send it urgently.", "stop")],
    )
    core.gateway = gateway
    session = core.new_session()
    reply = core.chat("Help me word a message to an overdue supplier", session)
    assert reply == "The delivery is overdue. Please send it urgently."
    assert len(calls) == 2 and calls[0]["max_tokens"] > 96
    assert calls[1]["messages"][-1]["content"] == "The delivery is"
    assert core.store.history(session)[1][-1]["content"] == reply


def test_continuation_removes_repeated_boundary_sentence(core):
    repeated = "The overdue components are needed urgently."
    gateway, calls = gateway_for(
        core.settings,
        [(repeated, "length"), (repeated + " Please confirm a dispatch date.", "stop")],
    )
    reply = "".join(
        gateway.respond("local_fast", [{"role": "user", "content": "Explain this"}], False)
    )
    assert reply == repeated + " Please confirm a dispatch date."
    assert len(calls) == 2


def test_large_output_continues_with_bounded_context_and_original_request(core):
    gateway, calls = gateway_for(
        core.settings, [("A" * 5000, "length"), ("B" * 4000, "length"), ("C", "stop")]
    )
    messages = [
        {"role": "system", "content": "Keep the requirements."},
        {"role": "user", "content": "Produce the full document."},
    ]
    reply = "".join(gateway.respond("local_fast", messages, False))
    assert reply == "A" * 5000 + "B" * 4000 + "C"
    for call in calls:
        assert call["messages"][:2] == messages
        assert token_bound(call["messages"]) + call["max_tokens"] + 128 <= 4096
    assert messages == calls[0]["messages"]  # The caller's request was not mutated.


def test_structured_draft_retries_whole_json_with_more_room(core):
    from nisha.workflows import EMAIL_SCHEMA

    body = (
        '{"subject":"Urgent delivery","body":"Please confirm when our overdue parts will arrive."}'
    )
    gateway, calls = gateway_for(
        core.settings, [('{"subject":"Urgent delivery","body":"Please', "length"), (body, "stop")]
    )
    assert (
        gateway.generate("local_fast", [{"role": "user", "content": "Email"}], EMAIL_SCHEMA) == body
    )
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]
    assert calls[1]["messages"] == calls[0]["messages"]
    assert all(call["response_format"]["type"] == "json_schema" for call in calls)


def test_repeated_unfinished_output_cannot_loop_or_be_stored(core):
    gateway, calls = gateway_for(
        core.settings, [("This incomplete response cannot make progress.", "length")]
    )
    core.gateway = gateway
    session = core.new_session()
    with pytest.raises(ModelUnavailable, match="progress"):
        core.chat("A question", session)
    assert len(calls) == 2 and not core.store.history(session)[1]


def test_closing_stream_does_not_start_a_continuation(core):
    gateway, calls = gateway_for(core.settings, [("Partial text", "length")])
    stream = gateway.respond("local_fast", [{"role": "user", "content": "Hi"}], True)
    assert next(stream) == "Partial text"
    stream.close()
    assert len(calls) == 1


def test_content_filter_is_distinct_from_output_limit_and_is_not_retried(core):
    gateway, calls = gateway_for(core.settings, [("Partial text", "content_filter")])
    with pytest.raises(ModelUnavailable, match="declined"):
        "".join(gateway.respond("local_fast", [{"role": "user", "content": "Hi"}], True))
    assert len(calls) == 1
