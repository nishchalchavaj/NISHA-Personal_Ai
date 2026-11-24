from io import BytesIO

import pytest
from PIL import Image

from nisha.errors import NishaError
from nisha.responsiveness import action_request
from nisha.screen import ScreenService, screen_question, visual_click_request


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


class FakeVisualVision:
    def __init__(self, location):
        self.location = location
        self.locate_calls = []
        self.describe_calls = []

    def locate(self, data, target):
        self.locate_calls.append((data[:2], target))
        return self.location

    def describe(self, data, question=None):
        self.describe_calls.append(question)
        return "A notes app is now visible."


class FakePointController:
    def __init__(self, size=(100, 80)):
        self.size = size
        self.calls = []

    def click_point(self, x, y, width, height):
        self.calls.append((x, y, width, height))


class FakeVirtualPointController:
    def __init__(self):
        self.calls = []

    def click_virtual_point(self, x, y, bounds):
        self.calls.append((x, y, bounds))


def test_visual_click_uses_local_location_once_and_checks_new_screenshot():
    initial = Image.new("RGB", (100, 80), "black")
    frames = [initial, initial.copy(), Image.new("RGB", (100, 80), "white")]
    vision = FakeVisualVision({
        "found": True, "x": 0.5, "y": 0.25, "confidence": 0.95, "evidence": "Search icon"
    })
    controller = FakePointController()
    service = ScreenService(
        "http://127.0.0.1:11434", capture=lambda: frames.pop(0),
        vision_factory=lambda url, model: vision,
    )

    result = service.visual_click("Search icon", controller)

    assert controller.calls == [(50, 20, 100, 80)]
    assert len(vision.locate_calls) == 1
    assert vision.locate_calls[0][1] == "Search icon"
    assert vision.describe_calls == ["Briefly describe the current visible screen."]
    assert "screenshot changed" in result
    assert "local vision now sees" in result


def test_visual_click_maps_full_virtual_desktop_to_negative_origin_monitor():
    frames = [
        Image.new("RGB", (3000, 1000), "black"),
        Image.new("RGB", (3000, 1000), "black"),
        Image.new("RGB", (3000, 1000), "white"),
    ]
    bounds = (-1920, -100, 3000, 1000)
    vision = FakeVisualVision({
        "found": True, "x": 0.5, "y": 0.4, "confidence": 0.99, "evidence": "Search icon"
    })
    controller = FakeVirtualPointController()
    service = ScreenService(
        "http://127.0.0.1:11434",
        capture=lambda: frames.pop(0),
        vision_factory=lambda url, model: vision,
        screen_bounds=lambda: bounds,
    )

    service.visual_click("Search icon", controller)

    assert controller.calls == [(-420, 300, bounds)]


def test_visual_click_refuses_if_virtual_monitor_layout_changes():
    source = Image.new("RGB", (3000, 1000), "black")
    bounds = iter([(-1920, -100, 3000, 1000), (-1920, -200, 3000, 1000)])
    vision = FakeVisualVision({
        "found": True, "x": 0.5, "y": 0.5, "confidence": 0.99, "evidence": "Search icon"
    })
    controller = FakeVirtualPointController()
    service = ScreenService(
        "http://127.0.0.1:11434",
        capture=lambda: source.copy(),
        vision_factory=lambda url, model: vision,
        screen_bounds=lambda: next(bounds),
    )

    with pytest.raises(NishaError, match="screen changed"):
        service.visual_click("Search icon", controller)
    assert controller.calls == []


def test_visual_click_refuses_monitor_gaps():
    source = Image.new("RGB", (3000, 1000), "black")
    vision = FakeVisualVision({
        "found": True, "x": 0.5, "y": 0.5, "confidence": 0.99, "evidence": "Search icon"
    })
    controller = FakeVirtualPointController()
    service = ScreenService(
        "http://127.0.0.1:11434",
        capture=lambda: source.copy(),
        vision_factory=lambda url, model: vision,
        screen_bounds=lambda: (-1000, 0, 3000, 1000),
        monitor_regions=lambda: ((-1000, 0, 1000, 1000), (1000, 0, 1000, 1000)),
    )

    with pytest.raises(NishaError, match="gap between monitors"):
        service.visual_click("Search icon", controller)
    assert controller.calls == []


@pytest.mark.parametrize("location", [
    {"found": False, "confidence": 0, "evidence": ""},
    {"found": True, "x": 0.5, "y": 0.5, "confidence": 0.89, "evidence": "Search"},
    {"found": True, "x": 8, "y": 0.5, "confidence": 0.99, "evidence": "Search"},
    {"found": True, "x": 0.5, "y": 0.5, "confidence": 0.99, "evidence": "Delete button"},
])
def test_visual_click_refuses_ambiguous_or_sensitive_targets_before_input(location):
    source = Image.new("RGB", (100, 80), "black")
    vision = FakeVisualVision(location)
    controller = FakePointController()
    service = ScreenService(
        "http://127.0.0.1:11434", capture=lambda: source.copy(),
        vision_factory=lambda url, model: vision,
    )

    with pytest.raises(NishaError):
        service.visual_click("Search icon", controller)
    assert controller.calls == []


@pytest.mark.parametrize("target", ["Submit payment", "Sign-in button", "unsubscribe link"])
def test_visual_click_sensitive_request_never_captures_or_acts(target):
    controller = FakePointController()
    service = ScreenService("http://127.0.0.1:11434", capture=lambda: pytest.fail("capture called"))
    with pytest.raises(NishaError, match="sensitive"):
        service.visual_click(target, controller)
    assert controller.calls == []


def test_visual_click_with_no_visible_change_does_not_retry():
    source = Image.new("RGB", (100, 80), "black")
    vision = FakeVisualVision({
        "found": True, "x": 0.5, "y": 0.5, "confidence": 0.99, "evidence": "Settings icon"
    })
    controller = FakePointController()
    service = ScreenService(
        "http://127.0.0.1:11434", capture=lambda: source.copy(),
        vision_factory=lambda url, model: vision,
    )
    result = service.visual_click("Settings icon", controller)
    assert len(controller.calls) == 1
    assert "no visible screen change" in result
    assert vision.describe_calls == []


def test_visual_click_refuses_stale_coordinates_if_screen_changes_during_model_call():
    frames = [
        Image.new("RGB", (100, 80), "black"),
        Image.new("RGB", (100, 80), "white"),
    ]
    vision = FakeVisualVision({
        "found": True, "x": 0.5, "y": 0.5, "confidence": 0.99, "evidence": "Search icon"
    })
    controller = FakePointController()
    service = ScreenService(
        "http://127.0.0.1:11434", capture=lambda: frames.pop(0),
        vision_factory=lambda url, model: vision,
    )
    with pytest.raises(NishaError, match="screen changed"):
        service.visual_click("Search icon", controller)
    assert controller.calls == []


@pytest.mark.parametrize("text,target", [
    ("click the search icon on screen", "the search icon"),
    ("tap on the blue button on my screen", "the blue button"),
    ("click Save in Notepad", None),
])
def test_visual_click_request_parser(text, target):
    assert visual_click_request(text) == target


def test_visual_click_routes_as_explicit_action_and_uses_local_service(core):
    from nisha.responsiveness import action_request

    session = core.new_session()
    calls = []
    core.screen.visual_click = lambda target, controller: calls.append((target, controller)) or "clicked"
    phrase = "click the search icon on screen"

    assert action_request(phrase)
    assert core.handle_action(phrase, session, [], "local_fast") == "clicked"
    assert calls == [("the search icon", core.pc_control)]
