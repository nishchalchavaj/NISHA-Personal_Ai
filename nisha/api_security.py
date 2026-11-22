"""Local API boundary: bounded JSON input and non-executable private responses."""

import asyncio
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = 1_048_576
RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


class LocalApiBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in RESPONSE_HEADERS.items():
                    headers[key] = value
            await send(message)

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, secure_send)

        headers = Headers(scope=scope)
        if len(headers.getlist("host")) != 1 or len(headers.getlist("origin")) > 1:
            await reject(400, "Ambiguous request headers are not permitted.")
            return
        host = headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid = (
                parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
            )
            if parsed.port is not None:
                valid = valid and 0 < parsed.port < 65536
        except ValueError:
            valid = False
        if not valid:
            await reject(400, "A loopback Host header is required.")
            return
        origin = headers.get("origin")
        if (
            origin is not None
            and origin.casefold() != (scope.get("scheme", "http") + "://" + host).casefold()
        ):
            await reject(403, "Cross-origin browser requests are not permitted.")
            return
        lengths = headers.getlist("content-length")
        try:
            if len(lengths) > 1 or (lengths and (not lengths[0].isdigit())):
                raise ValueError("Invalid length")
            if lengths and int(lengths[0]) > MAX_REQUEST_BYTES:
                await reject(413, "Request body exceeds the 1 MiB limit.")
                return
        except ValueError:
            await reject(400, "Invalid request length.")
            return
        content_type = headers.get("content-type", "").split(";", 1)[0].casefold().strip()
        if content_type and content_type != "application/json":
            await reject(415, "This API accepts JSON only; file uploads are not supported.")
            return
        body = bytearray()
        try:
            async with asyncio.timeout(15):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > MAX_REQUEST_BYTES:
                        await reject(413, "Request body exceeds the 1 MiB limit.")
                        return
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "Request body timed out.")
            return
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, secure_send)
