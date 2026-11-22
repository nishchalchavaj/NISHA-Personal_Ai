from contextlib import contextmanager

import httpx
import pytest

from nisha.errors import ModelUnavailable
from nisha.gateway import Gateway
from nisha.services import LocalServices


class SimulatedServices(LocalServices):
    def __init__(self, settings, initial=None, delay=0):
        self.time = 0
        super().__init__(settings, clock=lambda: self.time, wait=self.advance)
        self.available = dict(initial or {})
        self.launched = []
        self.delay = delay

    def advance(self, seconds):
        self.time += seconds

    def probe(self):
        state = {n: self.available.get(n, "unavailable") for n in ("ollama", "gateway")}
        for name, started in self.launched:
            if self.time - started >= self.delay:
                state[name] = "ready"
                self.available[name] = "ready"
        return dict(state, ready=all(s == "ready" for s in state.values()))

    @contextmanager
    def startup_lock(self):
        yield True

    def launch(self, name):
        self.launched.append((name, self.time))
        return True


def test_cold_services_start_in_order_without_waiting_in_gui(core):
    services = SimulatedServices(core.settings, delay=4)
    try:
        assert services.ensure(timeout=12)["ready"]
        assert [n for n, _ in services.launched] == ["ollama", "gateway"]
        assert services.launched[1][1] >= 4
        services.ensure()
        assert len(services.launched) == 2
    finally:
        services.close()


def test_retry_after_slow_boot_and_no_download_or_replacement(core):
    services = SimulatedServices(core.settings, delay=40)
    try:
        assert not services.ensure(timeout=1)["ready"]
        services.advance(40)
        services.delay = 0
        assert services.ensure()["ready"]
        assert [n for n, _ in services.launched].count("ollama") == 1
        services.available["ollama"] = "missing downloaded models"
        services.launched = []
        assert not services.ensure()["ready"] and not services.launched
        services.available = {"ollama": "ready", "gateway": "access/configuration error"}
        assert not services.ensure()["ready"] and not services.launched
    finally:
        services.close()


def test_cancellation_does_not_launch_services(core):
    services = SimulatedServices(core.settings)
    try:
        assert not services.ensure(cancelled=lambda: True)["ready"]
        assert not services.launched
    finally:
        services.close()


@pytest.mark.parametrize("code,recovered", [(503, True), (401, False)])
def test_gateway_retries_only_recoverable_local_request_before_output(core, code, recovered):
    calls, recoveries = [], []

    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(code, text="PRIVATE PROVIDER RESPONSE")
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"Ready."}}]}\n\ndata: [DONE]\n\n'
        )

    class Services:
        def ensure(self):
            recoveries.append(True)
            return {"ready": True}

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = Gateway(core.settings, client, Services())
        if recovered:
            assert gateway.complete("local_fast", []) == "Ready."
            assert len(calls) == 2 and recoveries == [True]
        else:
            with pytest.raises(ModelUnavailable) as error:
                gateway.complete("local_fast", [])
            assert "PRIVATE" not in str(error.value)
            assert len(calls) == 1 and not recoveries


def test_partial_broken_stream_is_recorded_without_retry_or_complete_exchange(core):
    core.gateway.fail = True
    session = core.new_session()
    stream = core.stream("Explain photosynthesis", session)
    assert next(stream) == "Hello "
    with pytest.raises(ModelUnavailable):
        next(stream)
    assert len(core.gateway.calls) == 1 and not core.store.history(session)[1]
    with core.store.connect() as db:
        result = db.execute("SELECT * FROM turn_outcomes").fetchone()
    assert result["status"] == "failed" and result["detail"] == "ModelUnavailable"
    assert result["request"] == "Explain photosynthesis"


def test_status_question_needs_no_model_or_images(core):
    core.gateway.fail = True
    assert "ready" in core.chat("what are you doing, Nisha?", core.new_session())
    assert not core.gateway.calls


def test_corrected_user_name_is_saved_without_the_rejected_name(core):
    core.chat("My name is not Nishal, it's Nishchal.", core.new_session())
    name = next(m for m in core.store.memories() if m["key"] == "profile:name")
    assert name["text"] == "User's name is Nishchal."


def test_gateway_does_not_replay_a_partial_transport_failure(core):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n'
            raise httpx.ReadError("Disconnected")

    class Services:
        def ensure(self):
            pytest.fail("A partial answer must not be silently replayed")

    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        return httpx.Response(200, stream=BrokenStream())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        stream = Gateway(core.settings, client, Services()).stream("local_fast", [])
        assert next(stream) == "Partial"
        with pytest.raises(ModelUnavailable):
            next(stream)
