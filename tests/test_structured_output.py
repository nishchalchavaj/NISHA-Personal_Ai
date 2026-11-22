import json

import httpx
import pytest

from nisha.errors import ModelUnavailable, PrivacyError
from nisha.gateway import Gateway
from nisha.workflows import EMAIL_SCHEMA


def client_for_response(finish="stop"):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        events = [
            json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "content": '{"subject":"Hello","body":"Approved draft body"}'
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            ),
            json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}),
            "[DONE]",
        ]
        return httpx.Response(200, text="".join("data: " + event + "\n\n" for event in events))

    return httpx.Client(transport=httpx.MockTransport(respond)), requests


def test_local_drafts_request_schema_not_prompt_only_json(core):
    client, requests = client_for_response()
    gateway = Gateway(core.settings, client)
    content = gateway.generate(
        "local_fast", [{"role": "user", "content": "Synthetic email"}], schema=EMAIL_SCHEMA
    )
    assert json.loads(content)["body"] == "Approved draft body"
    payload = json.loads(requests[-1].content)
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == EMAIL_SCHEMA
    assert requests[0].url.host == "127.0.0.1" and requests[-1].url.host == "127.0.0.1"


def test_truncated_artifact_is_rejected_even_after_done_marker(core):
    client, _ = client_for_response("length")
    gateway = Gateway(core.settings, client)
    with pytest.raises(ModelUnavailable, match="before completing"):
        gateway.generate(
            "local_fast", [{"role": "user", "content": "Synthetic email"}], schema=EMAIL_SCHEMA
        )


def test_structured_generation_cannot_route_to_external_base(core):
    with pytest.raises(PrivacyError):
        core.generate_content("Email", core.new_session(), "cloud", "JSON only", EMAIL_SCHEMA)
