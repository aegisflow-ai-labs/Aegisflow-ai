"""Bound HTTP input before authentication dependencies and JSON parsing."""

import anyio
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestLimits:
    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int = 65536,
        max_header_bytes: int = 16384,
        read_timeout_seconds: float = 5.0,
    ) -> None:
        if max_body_bytes <= 0 or max_header_bytes <= 0 or read_timeout_seconds <= 0:
            raise ValueError("Request limits must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_header_bytes = max_header_bytes
        self.read_timeout_seconds = read_timeout_seconds

    async def reject(
        self, scope: Scope, receive: Receive, send: Send, status: int, code: str
    ) -> None:
        response = JSONResponse(
            status_code=status,
            content={"detail": code},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        if sum(len(name) + len(value) for name, value in headers) > self.max_header_bytes:
            await self.reject(scope, receive, send, 431, "REQUEST_HEADERS_TOO_LARGE")
            return
        lengths = [value for name, value in headers if name.lower() == b"content-length"]
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                await self.reject(scope, receive, send, 400, "INVALID_CONTENT_LENGTH")
                return
            # Compare digit strings before int conversion, including absurd lengths.
            declared = lengths[0].lstrip(b"0") or b"0"
            limit = str(self.max_body_bytes).encode()
            if len(declared) > len(limit) or (len(declared) == len(limit) and declared > limit):
                await self.reject(scope, receive, send, 413, "REQUEST_TOO_LARGE")
                return
        body_buffer = bytearray()
        size = 0
        try:
            with anyio.fail_after(self.read_timeout_seconds):
                while True:
                    await anyio.lowlevel.checkpoint()
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > self.max_body_bytes:
                        break
                    body_buffer.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await self.reject(scope, receive, send, 408, "REQUEST_TIMEOUT")
            return
        if size > self.max_body_bytes:
            await self.reject(scope, receive, send, 413, "REQUEST_TOO_LARGE")
            return
        if lengths and size != int(declared):
            await self.reject(scope, receive, send, 400, "INVALID_CONTENT_LENGTH")
            return
        body = bytes(body_buffer)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
