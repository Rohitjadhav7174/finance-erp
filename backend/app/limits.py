"""Rejects request bodies over a size limit WHILE they arrive (before parsing), so a huge
upload cannot exhaust the server's memory or disk."""
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY = 6 * 1024 * 1024  # largest allowed: a 5 MB Excel file plus form overhead


class BodyTooLarge(Exception):
    pass


class BodySizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY):
        self.app, self.max = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max:
            return await _reject(send)
        seen = 0

        async def limited() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max:
                    raise BodyTooLarge()
            return msg
        try:
            await self.app(scope, limited, send)
        except BodyTooLarge:
            await _reject(send)


async def _reject(send: Send) -> None:
    body = b'{"detail":"The request is too large (maximum 5 MB file).","code":"too_large"}'
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
