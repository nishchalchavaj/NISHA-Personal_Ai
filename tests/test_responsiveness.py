import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import httpx
import pytest

from nisha.errors import OperationCancelled
from nisha.responsiveness import action_request
from nisha.services import LocalServices


@pytest.mark.parametrize(
    "text", ["Hello", "What's up, baby?", "Hi Nisha", "How are you?", "Thank you"]
)
def test_simple_smalltalk_needs_no_model_or_service(core, text):
    core.settings.instant_smalltalk = True
    core.gateway.fail = True
    started = monotonic()
    assert core.chat(text, core.new_session())
    assert not core.gateway.calls
    assert monotonic() - started < 1


@pytest.mark.parametrize(
    "text", ["Hello, open YouTube", "How are you handling code?", "What's up with my order?"]
)
def test_complex_messages_are_not_replaced_with_greetings(core, text):
    from nisha.responsiveness import quick_reply

    assert quick_reply(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "close",
        "close your mouth",
        "approve email deadbeef",
        "send it",
        "Hello",
        "Explain how to open a folder",
    ],
)
def test_controls_approvals_and_conversation_never_auto_dispatch(core, text):
    assert not action_request(text)


def test_background_action_does_not_block_conversation_and_cancel_is_thread_local(
    core, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    core.settings.instant_smalltalk = True

    def action(*args):
        entered.set()
        assert release.wait(4)
        core.check_cancelled()
        return "Completed the synthetic action."

    monkeypatch.setattr(core, "handle_action", action)
    session = core.new_session()
    with ThreadPoolExecutor(max_workers=2) as pool:
        background = pool.submit(
            core.background_action, "Open synthetic app", session, "auto", lambda: False
        )
        assert entered.wait(2)
        try:
            reply = pool.submit(core.chat, "Hello", session).result(timeout=1)
            assert reply and not core.gateway.calls
            generated = pool.submit(core.chat, "What is gravity?", session).result(timeout=1)
            assert generated == "Hello Nishchal."
        finally:
            release.set()
        assert "Completed" in background.result(timeout=2)


def test_cancelled_background_action_cannot_execute_or_report_success(core, monkeypatch):
    monkeypatch.setattr(
        core, "handle_action", lambda *args: pytest.fail("Cancelled action executed")
    )
    session = core.new_session()
    with pytest.raises(OperationCancelled):
        core.background_action("Open synthetic app", session, cancelled=lambda: True)
    assert not core.store.history(session)[1]
    assert core._cancelled is None


def test_warmup_is_local_bounded_and_skips_loaded_models(core):
    calls = []

    def transport(request):
        calls.append(request)
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        return httpx.Response(200, json={"done": True})

    services = LocalServices(core.settings)
    try:
        services.warm_fast(transport=httpx.MockTransport(transport))
        assert [r.url.path for r in calls] == ["/api/ps", "/api/show", "/api/chat"]
        assert b'"num_predict":1' in calls[-1].content
        assert all(r.url.host == "127.0.0.1" for r in calls)
        calls.clear()
        services.warm_fast(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"models": [{"name": "already loaded"}]})
            )
        )
    finally:
        services.close()


def test_warmup_cancels_without_waiting_for_model_load(core):
    stopped = threading.Event()

    async def transport(request):
        stopped.set()
        await asyncio.sleep(10)
        return httpx.Response(200, json={"models": []})

    services = LocalServices(core.settings)
    try:
        started = monotonic()
        services.warm_fast(cancelled=stopped.is_set, transport=httpx.MockTransport(transport))
        assert monotonic() - started < 1
    finally:
        services.close()


def test_repeated_startup_does_not_launch_duplicate_process(core, monkeypatch):
    from types import SimpleNamespace

    from nisha import services as module

    monkeypatch.setattr(module, "_STARTING", {})
    launched = []
    process = SimpleNamespace(poll=lambda: None)
    services = LocalServices(
        core.settings, launcher=lambda *args, **kwargs: launched.append(args) or process
    )
    monkeypatch.setattr(services, "ollama_executable", lambda: "synthetic-ollama.exe")
    try:
        assert services.launch("ollama") and services.launch("ollama")
        assert len(launched) == 1
        process.poll = lambda: 1
        assert services.launch("ollama") and len(launched) == 2
    finally:
        services.close()


def test_stress_mixed_background_actions_and_conversations(core, monkeypatch):
    core.settings.instant_smalltalk = True
    calls = []
    monkeypatch.setattr(
        core, "handle_action", lambda text, *args: calls.append(text) or "Completed synthetic task."
    )
    session = core.new_session()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(core.background_action, f"Open synthetic {index}", session)
            if index % 5 == 0
            else pool.submit(core.chat, "Hello", session)
            for index in range(120)
        ]
        assert all(f.result(timeout=15) for f in futures)
    assert len(calls) == len(set(calls)) == 24
    assert len(core.store.history(session)[1]) == 240
    with core.store.connect() as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
