import httpx
import pytest

from nisha.media import MediaService, public_topic


@pytest.mark.parametrize(
    "text,topic",
    [
        ("Who is Nikola Tesla?", "Nikola Tesla"),
        ("Tell me about Paris", "Paris"),
        ("Show me images of Saturn", "Saturn"),
    ],
)
def test_public_topics_are_extracted_without_conversation(text, topic):
    assert public_topic(text) == topic


@pytest.mark.parametrize(
    "text",
    [
        "What is my password?",
        "Tell me about our project",
        "Who is alex@gmail.com?",
        "What is C:\\private\\notes.txt",
        "Open YouTube",
        "What is my medical appointment?",
        "What are you doing?",
        "What are you doing, Nisha?",
        "Who are you?",
    ],
)
def test_private_or_action_queries_do_not_trigger_public_lookup(tmp_path, text):
    assert public_topic(text) is None
    service = MediaService(
        tmp_path,
        httpx.Client(
            transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected public lookup"))
        ),
    )
    assert service.find(text) == []


def test_local_generated_media_preferred_and_private_lookup_suppressed(tmp_path):
    folder = tmp_path / "generated"
    folder.mkdir()
    (folder / "saturn_diagram.png").write_bytes(b"synthetic")
    service = MediaService(
        tmp_path,
        httpx.Client(
            transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected public lookup"))
        ),
    )
    found = service.find("Tell me about Saturn", private=True)
    assert found[0].kind == "image" and "Generated media" in found[0].caption
    assert service.find("Who is Alex?", private=True) == []


def test_public_image_lookup_falls_back_and_keeps_attribution(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "en.wikipedia.org":
            return httpx.Response(403)
        assert request.url.params["q"] == "Nikola Tesla portrait"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Nikola Tesla",
                        "thumbnail": "https://api.openverse.org/v1/images/test/thumb/",
                        "foreign_landing_url": "https://example.org/photo",
                        "creator": "Creator",
                        "license": "by",
                        "license_version": "4.0",
                    }
                ]
            },
        )

    service = MediaService(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    found = service.find("Who is Nikola Tesla?")
    assert found[0].source == "https://example.org/photo" and "Creator" in found[0].caption
    assert len(calls) == 2 and not service.wiki_available


def test_unsafe_thumbnail_from_public_response_is_ignored(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {"title": "Unsafe", "thumbnail": {"source": "http://127.0.0.1/private"}}
                    ]
                },
                "results": [{"thumbnail": "http://127.0.0.1/private"}],
            },
        )

    service = MediaService(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    assert service.find("Tell me about Saturn") == []


def test_wikipedia_image_must_match_topic_and_smalltalk_cannot_match_local_files(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "Portal robots",
                            "thumbnail": {"source": "https://upload.wikimedia.org/robot.png"},
                        },
                        {
                            "title": "Saturn",
                            "thumbnail": {"source": "https://upload.wikimedia.org/saturn.png"},
                        },
                    ]
                }
            },
        )

    service = MediaService(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    assert [asset.title for asset in service.find("Tell me about Saturn")] == ["Saturn"]
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated/doing_robot.png").write_bytes(b"synthetic")
    assert service.find("What are you doing?") == []
