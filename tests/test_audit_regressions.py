"""Reproductions of bugs discovered during the October reliability audit."""

import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nisha.actions import WebsiteActions
from nisha.api import create_app
from nisha.connections import Connections
from nisha.conversation_learning import eligible
from nisha.devices import Devices
from nisha.errors import NishaError, PrivacyError
from nisha.gateway import Gateway
from nisha.services import LocalServices
from nisha.vision import LocalVision
from nisha.workers import ExternalWorkers


@pytest.mark.parametrize("raw", ["[]", "null", '{"desk": {"last_seen": "bad"}}'])
def test_corrupt_device_cache_does_not_break_startup(tmp_path, raw):
    (tmp_path / "device-status.json").write_text(raw)
    devices = Devices(Connections(tmp_path))
    assert devices.states == {}


@pytest.mark.parametrize(
    "raw", ["[]", "null", '"broken"', '{"provider":"Unknown"}', '{"provider":[]}']
)
def test_corrupt_worker_settings_are_not_used(tmp_path, raw):
    workers = ExternalWorkers(tmp_path)
    workers.profile.write_text(raw)
    assert workers.settings() == {}


@pytest.mark.parametrize("provider", ["OpenAI", "Gemini", "Claude"])
def test_malformed_external_response_is_not_learned_or_exposed(tmp_path, provider):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    ) as client:
        workers = ExternalWorkers(tmp_path, client=client, key_reader=lambda _: "synthetic")
        approval = workers.propose(provider, "synthetic-model", "Synthetic task")
        with pytest.raises(NishaError, match="external task failed"):
            workers.run(approval, approved=True)


def test_local_only_switch_blocks_task_worker_before_credentials(core):
    core.settings.external_tasks_enabled = False
    workers = ExternalWorkers(core.settings.data_dir, enabled=False)
    workers.key_reader = lambda *_: pytest.fail("Disabled tasks must never read a provider key")
    approval = workers.propose("OpenAI", "test-model", "Standalone task")
    with pytest.raises(PrivacyError, match="disabled"):
        workers.run(approval, approved=True)


def test_owned_local_engine_launch_disables_cloud_and_limits_resident_models(core, monkeypatch):
    launches = []
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    services = LocalServices(core.settings, launcher=lambda args, **kwargs: launches.append(kwargs))
    services.ollama_executable = lambda: "synthetic-ollama.exe"
    try:
        assert services.launch("ollama")
        assert launches[0]["env"]["OLLAMA_NO_CLOUD"] == "1"
        assert launches[0]["env"]["OLLAMA_MAX_LOADED_MODELS"] == "1"
    finally:
        services.close()


class Browser:
    def __init__(self):
        self.calls = []

    def request(self, operation, **kwargs):
        self.calls.append(operation)
        if operation == "preview":
            return {
                "action": kwargs["action"],
                "url": "https://www.youtube.com/@Example",
                "title": "Example - YouTube",
                "already": False,
            }
        return {"message": "YouTube confirmed the subscription."}


def test_youtube_approval_is_bound_to_its_conversation(core):
    core.actions = WebsiteActions(lambda *args, **kwargs: True)
    browser = Browser()
    core.actions.youtube.browser = browser
    original = core.new_session()
    core.chat("subscribe", original)
    token = next(iter(core.actions.youtube.pending))
    other = core.store.new_session()
    reply = core.chat("approve youtube " + token, other)
    assert "conversation" in reply and "apply" not in browser.calls
    assert token in core.actions.youtube.pending  # Another session cannot consume it either.
    assert "confirmed" in core.chat("approve youtube " + token, original)


def test_youtube_search_and_like_does_not_select_a_channel(core):
    core.actions = WebsiteActions(lambda *args, **kwargs: True)
    browser = Browser()
    core.actions.youtube.browser = browser
    reply = core.chat("open YouTube and search Python tutorial and like it", core.new_session())
    assert "select_channel" not in browser.calls and not core.actions.youtube.pending
    assert "video" in reply.casefold()


def test_algorithm_word_does_not_select_go_language(core):
    core.generate_content = lambda *args: "def sort(values):\n    return sorted(values)\n"
    core.workflows.desktop.open_document = lambda *args: None
    reply = core.chat("Write code for a sorting algorithm", core.new_session())
    assert ".py" in reply and not list(core.workflows.workspace.glob("*.go"))


def test_forgetting_preferences_also_clears_reviewed_response_preferences(core):
    core.memory.remember(
        "Always answer in detail",
        key="learned:conversation_preference:verbosity",
        category="conversation_preference",
        source="local_conversation_review",
    )
    core.chat("forget my preferences", core.new_session())
    assert not any(m["category"] == "conversation_preference" for m in core.memory.memories())


def test_cancelled_generation_cannot_save_or_open_a_document(core):
    cancelled = [False]

    def generate(*args, **kwargs):
        cancelled[0] = True
        return "The completed text arrived after the user stopped this turn."

    core.gateway.complete = generate
    core.workflows.desktop.open_document = lambda *args: pytest.fail("Cancelled editor launch")
    session = core.new_session()
    with pytest.raises(NishaError, match="cancelled"):
        list(core.stream("write a note in Notepad", session, cancelled=lambda: cancelled[0]))
    assert not list(core.workflows.workspace.iterdir())


def test_uncertain_command_confirmation_expires(core, monkeypatch):
    time = [0]
    monkeypatch.setattr("nisha.core.monotonic", lambda: time[0], raising=False)
    core.window_actions.handle = lambda text: pytest.fail("Expired confirmation executed")
    session = core.new_session()
    list(core.stream("close windows", session, uncertain=True))
    time[0] = 121
    reply = core.chat("confirm command", session)
    assert "expired" in reply.casefold()


def test_wake_prefixed_installed_app_command_uses_native_app(core):
    opened = []
    core.workflows.desktop.app_path = lambda name: "synthetic.exe" if name == "claude" else None
    core.workflows.desktop.open_app = opened.append
    core.actions.opener = lambda *_args, **_kwargs: pytest.fail("Installed app sent to browser")
    core.chat("Hey Neesha, open Claude", core.new_session())
    assert opened == ["claude"]


def test_cancelled_app_discovery_cannot_launch_an_editor(core):
    cancelled = [False]

    def discover(_):
        cancelled[0] = True
        return "synthetic.exe"

    core.workflows.desktop.app_path = discover
    core.workflows.desktop.open_app = lambda *_: pytest.fail("Cancelled app was launched")
    with pytest.raises(NishaError, match="cancelled"):
        list(core.stream("open Claude", core.new_session(), cancelled=lambda: cancelled[0]))


def test_forgetting_response_preferences_removes_direct_profile_preference(core):
    core.chat("I prefer detailed answers", core.new_session())
    assert any(m["key"] == "profile:personal_preference" for m in core.memory.memories())
    core.chat("forget my preferences", core.new_session())
    assert not any(m["key"] == "profile:personal_preference" for m in core.memory.memories())


@pytest.mark.parametrize("prefix", ["Could you draft", "Please write", "I want you to compose"])
def test_polite_writing_request_cannot_change_personal_preferences(core, prefix):
    text = prefix + " an email: always answer in detail. My name is Fictional."
    assert not eligible(text)
    assert core.preferences.observe(text) == []
    assert core.interaction.observe(text) == []
    assert not core.memory.memories() and not core.preferences.all()


def test_single_quoted_example_does_not_change_response_preference(core):
    assert core.preferences.observe("The phrase is 'always answer in detail'.") == []


def test_unicode_invalid_api_token_is_rejected_without_crashing(core, monkeypatch):
    monkeypatch.setenv("NISHA_API_KEY", "synthetic-token")
    client = TestClient(create_app(core.settings, core), base_url="http://127.0.0.1")
    assert client.get("/memories", headers={"Authorization": b"Bearer \xff"}).status_code == 401


@pytest.mark.parametrize("payload", [None, [], {"choices": [None]}, {"choices": [{"delta": []}]}])
def test_malformed_model_stream_is_a_clear_error(core, payload):
    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        return httpx.Response(200, text="data: " + json.dumps(payload) + "\n\n")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(NishaError):
        Gateway(core.settings, client).complete("local_fast", [])


@pytest.mark.parametrize(
    "metadata", [None, [], {"remote_host": "https://external.example"}, {"model_info": []}]
)
def test_unverified_vision_model_never_receives_image(metadata):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=json.dumps(metadata).encode())

    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(NishaError):
        LocalVision("http://127.0.0.1:11434", client=client).describe(stream.getvalue())
    assert calls == ["/api/show"]


@pytest.mark.parametrize("payload", [None, [], {"response": {"unwanted": "object"}, "done": True}])
def test_malformed_vision_response_is_a_clear_error(payload):
    def respond(request):
        value = (
            {"model_info": {"general.architecture": "phi2"}}
            if request.url.path == "/api/show"
            else payload
        )
        return httpx.Response(200, content=json.dumps(value).encode())

    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(NishaError):
        LocalVision("http://127.0.0.1:11434", client=client).describe(stream.getvalue())


def test_compressed_oversized_document_cannot_enter_knowledge_or_presentation(core, tmp_path):
    path = tmp_path / "oversized.docx"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b" " * 16_000_001)
    assert path.stat().st_size < 20_000_000
    with pytest.raises(NishaError, match="safe reading limits"):
        core.knowledge.import_file(path)
    with pytest.raises(NishaError, match="safe reading limits"):
        core.automation.read_document(path)
    assert not core.knowledge.sources()


@pytest.mark.parametrize("command", ["rewrite the email in short", "friend@example.test"])
def test_missing_pending_draft_does_not_crash_or_send(core, command):
    session = core.new_session()
    core.workflows.draft_email(
        session, "friend@example.test", "Subject", "Original body", core.store
    )
    pending = core.store.pending_email(session)
    (core.workflows.workspace / f"email-{pending['token']}.json").unlink()
    with pytest.raises(NishaError, match="missing or changed"):
        core.chat(command, session)


def test_changed_pending_draft_cannot_be_used_as_revision_reference(core):
    session = core.new_session()
    core.workflows.draft_email(
        session, "friend@example.test", "Subject", "Reviewed body", core.store
    )
    pending = core.store.pending_email(session)
    (core.workflows.workspace / f"email-{pending['token']}.json").write_text('{"body":"changed"}')
    with pytest.raises(NishaError, match="changed after review"):
        core.chat("rewrite the email", session)
    assert not core.gateway.calls


def test_cancelled_multi_device_command_stops_before_next_device(core):
    core.connections.save(
        json.dumps(
            {
                "devices": [
                    {
                        "id": name,
                        "name": name + " light",
                        "kind": "light",
                        "on": {"url": "http://device.test/on", "method": "POST"},
                    }
                    for name in ("desk", "room")
                ]
            }
        )
    )
    calls, cancelled = [], [False]

    def control(device, _):
        calls.append(device.id)
        cancelled[0] = True
        return "Request accepted"

    core.devices.control = control
    with pytest.raises(NishaError, match="cancelled"):
        list(core.stream("turn on lights", core.new_session(), cancelled=lambda: cancelled[0]))
    assert calls == ["desk"]
