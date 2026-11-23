import json

import httpx
import pytest

from nisha.errors import NishaError
from nisha.responsiveness import action_request


def configured_search(core, endpoint):
    core.connections.save(json.dumps({"search_url": endpoint}))


def test_web_research_sends_only_explicit_query_and_returns_public_cited_evidence(core):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Primary guide",
                        "url": "https://docs.example.org/guide",
                        "content": "Observed result, TOKEN=private-value",
                    },
                    {
                        "title": "Private endpoint",
                        "url": "http://127.0.0.1/private",
                        "content": "must not surface",
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    core.research_agent = type(core.research_agent)(core.connections, client=client, store=core.store)
    configured_search(core, "http://127.0.0.1:8080/search")

    result = core.research_agent.search("Python Windows Job Object limits")

    assert len(requests) == 1
    assert requests[0].url.params["q"] == "Python Windows Job Object limits"
    assert "format=json" in str(requests[0].url)
    assert result["source_count"] == 1
    assert result["sources"][0]["url"] == "https://docs.example.org/guide"
    assert "[REDACTED]" in result["sources"][0]["snippet"]
    assert "no project files or conversation history attached" in result["scope"]
    client.close()


def test_web_research_requires_configured_endpoint_without_network_request(core):
    with pytest.raises(NishaError, match="No request was sent"):
        core.research_agent.search("current Python documentation")


def test_web_research_voice_route_uses_existing_action_dispatch(core):
    assert action_request("Nisha, web research for Windows Job Objects")
