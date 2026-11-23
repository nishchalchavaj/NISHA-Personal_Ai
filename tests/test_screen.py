from io import BytesIO

import pytest
from PIL import Image

from nisha.errors import NishaError
from nisha.responsiveness import action_request
from nisha.screen import ScreenService, screen_question


def test_screen_capture_is_bounded_jpeg():
    source = Image.new("RGB", (320, 200), "teal")
    service = ScreenService("http://127.0.0.1:11434", capture=lambda: source)
    data = service.capture()
    with Image.open(BytesIO(data)) as decoded:
        assert decoded.format == "JPEG"
        assert decoded.size == (320, 200)
    assert len(data) < 100_000


def test_screen_capture_rejects_oversized_source():
    class LargeImage:
        width = 5000
        height = 5000

    service = ScreenService("http://127.0.0.1:11434", capture=LargeImage)
    with pytest.raises(NishaError, match="size limit"):
        service.capture()


def test_screen_analysis_uses_only_injected_local_vision():
    source = Image.new("RGB", (64, 64), "black")
    received = {}

    class FakeVision:
        def __init__(self, url, model):
            received["provider"] = (url, model)

        def describe(self, data, question=None):
            received["image"] = Image.open(BytesIO(data)).format
            received["question"] = question
            return "A local editor window is visible."

    service = ScreenService(
        "http://127.0.0.1:11434", "moondream", capture=lambda: source,
        vision_factory=FakeVision,
    )
    assert service.analyze("Which app is open?") == "A local editor window is visible."
    assert received["provider"] == ("http://127.0.0.1:11434", "moondream")
    assert received["image"] == "JPEG"
    assert received["question"] == "Which app is open?"


@pytest.mark.parametrize(
    ("text", "question"),
    [
        ("What's on my screen?", ""),
        ("describe screen", ""),
        ("What does my screen show: which app is open?", "which app is open"),
        ("hello", None),
    ],
)
def test_screen_request_parser_and_action_routing(text, question):
    assert screen_question(text) == question
    assert action_request(text) is (question is not None)


def test_explicit_screen_command_routes_through_core_and_records_result(core):
    session = core.new_session()
    calls = []
    core.screen.analyze = lambda question: calls.append(question) or "A text editor is visible."
    assert core.handle_action("What's on my screen?", session, [], "local_fast") == (
        "A text editor is visible."
    )
    assert calls == [None]
