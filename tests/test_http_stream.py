import asyncio
import threading
from time import monotonic

import httpx
import pytest

from nisha.errors import OperationCancelled
from nisha.http_stream import cancellable_lines


def stream(transport, cancelled=lambda: False):
    return cancellable_lines("http://127.0.0.1/test", {}, {}, cancelled, transport=transport)


def test_cancels_before_headers_without_waiting_for_timeout():
    started, closed = threading.Event(), threading.Event()

    async def response(request):
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            closed.set()

    before = monotonic()
    with pytest.raises(OperationCancelled):
        list(stream(httpx.MockTransport(response), started.is_set))
    assert closed.is_set() and monotonic() - before < 1


class SlowBody(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = threading.Event()

    async def __aiter__(self):
        yield b"first\n"
        await asyncio.sleep(30)

    async def aclose(self):
        self.closed.set()


def test_cancels_between_tokens_and_releases_connection():
    body, stop = SlowBody(), threading.Event()
    lines = stream(httpx.MockTransport(lambda _: httpx.Response(200, stream=body)), stop.is_set)
    assert next(lines) == "first"
    stop.set()
    before = monotonic()
    with pytest.raises(OperationCancelled):
        next(lines)
    assert body.closed.is_set() and monotonic() - before < 1


def test_early_consumer_close_releases_a_saturated_queue():
    class ManyLines(SlowBody):
        async def __aiter__(self):
            for _ in range(10000):
                yield b"line\n"

    body = ManyLines()
    lines = stream(httpx.MockTransport(lambda _: httpx.Response(200, stream=body)))
    assert next(lines) == "line"
    before = monotonic()
    lines.close()
    assert body.closed.is_set() and monotonic() - before < 1
    assert not any(t.name == "nisha-response-io" for t in threading.enumerate())


def test_complete_stream_and_http_errors_reach_caller():
    assert list(stream(httpx.MockTransport(lambda _: httpx.Response(200, text="one\ntwo\n")))) == [
        "one",
        "two",
    ]
    with pytest.raises(httpx.HTTPStatusError):
        list(stream(httpx.MockTransport(lambda _: httpx.Response(503))))


def test_gateway_cancelled_before_any_network_or_recovery(core):
    from nisha.gateway import Gateway

    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected request"))
    ) as client:
        gateway = Gateway(core.settings, client)
        with gateway.cancellation(lambda: True), pytest.raises(OperationCancelled):
            list(gateway.stream("local_fast", []))
        assert getattr(gateway._thread_state, "cancelled", None) is None
