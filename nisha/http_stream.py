"""A synchronous stream backed by cancellable asynchronous network I/O."""

import asyncio
from queue import Empty, Full, Queue
from threading import Event, Thread

import httpx

from nisha.errors import OperationCancelled


def cancellable_lines(url, payload, headers, cancelled, timeout=180, transport=None):
    queue = Queue(maxsize=128)
    stopped = Event()

    async def deliver(kind, value):
        while not stopped.is_set():
            try:
                queue.put_nowait((kind, value))
                return
            except Full:
                await asyncio.sleep(0.01)

    async def request():
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout, connect=5), trust_env=False, transport=transport
                ) as client,
                client.stream("POST", url, headers=headers, json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    await deliver("line", line)
            await deliver("done", None)
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, OSError, ValueError, TypeError, RuntimeError) as exc:
            await deliver("error", exc)

    async def supervise():
        task = asyncio.create_task(request())
        try:
            while not task.done() and not stopped.is_set():
                await asyncio.sleep(0.05)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    worker = Thread(target=lambda: asyncio.run(supervise()), daemon=True, name="nisha-response-io")
    worker.start()
    try:
        while True:
            if cancelled and cancelled():
                raise OperationCancelled("Operation cancelled.")
            try:
                kind, value = queue.get(timeout=0.05)
            except Empty:
                if not worker.is_alive():
                    raise httpx.ReadError("The local response connection stopped.")
                continue
            if kind == "done":
                return
            if kind == "error":
                raise value
            yield value
    finally:
        stopped.set()
        worker.join(timeout=1)
