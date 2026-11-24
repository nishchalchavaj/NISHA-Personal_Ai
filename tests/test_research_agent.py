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


def test_latest_news_question_uses_live_search_and_reports_search_time(core):
    seen = []
    core.research_agent.live_news = lambda query: seen.append(query) or {
        "headlines": [{"title": "Market report", "source": "News", "url": "https://news.example.test/report", "published": "today"}],
        "searched_at": "2026-11-24T12:34:00+05:30",
    }
    query = "What is the latest news in market?"
    assert action_request(query)

    result = core.chat(query, core.new_session())

    assert seen == [query.rstrip("?")]
    assert "searched 2026-11-24T12:34" in result
    assert "https://news.example.test/report" in result
    assert not core.gateway.calls


def test_latest_news_network_failure_does_not_make_up_results(core):
    core.research_agent.live_news = lambda _query: (_ for _ in ()).throw(
        NishaError("I couldn't retrieve live news right now.")
    )
    result = core.chat("What is the latest news in market?", core.new_session())
    assert "couldn't retrieve live news" in result
    assert not core.gateway.calls


def test_live_news_rss_fetches_only_bounded_public_headline_metadata(core):
    requests = []
    rss = """<?xml version="1.0"?><rss><channel><item>
      <title>Market rises after policy update</title>
      <link>https://news.example.org/story</link><source>Example News</source>
      <pubDate>Tue, 24 Nov 2026 06:00:00 GMT</pubDate>
    </item></channel></rss>"""

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=rss)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    core.research_agent.client = client
    result = core.research_agent.live_news("latest market news")

    assert len(requests) == 1
    assert requests[0].url.host == "news.google.com"
    assert requests[0].url.params["q"] == "latest market news when:1d"
    assert len(result["headlines"]) == 1
    assert result["headlines"][0]["source"] == "Example News"
    assert "24 Nov 2026" in result["headlines"][0]["published"]
    assert "no conversation" in result["scope"]
    client.close()
