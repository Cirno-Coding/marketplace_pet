from starlette.datastructures import MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.application.tracing import (
    TRACE_ID_HEADER,
    attach_trace_id,
    reset_trace_id,
    resolve_trace_id,
    set_trace_id,
)

_TRACE_ID_HEADER_BYTES = TRACE_ID_HEADER.lower().encode("latin-1")


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        trace_id = resolve_trace_id(_incoming_trace_id(scope))
        response_started = False

        async def send_with_trace_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                MutableHeaders(scope=message)[TRACE_ID_HEADER] = trace_id
            await send(message)

        token = set_trace_id(trace_id)
        try:
            await self._app(scope, receive, send_with_trace_id)
        except Exception as exc:
            attach_trace_id(exc, trace_id)
            if not response_started:
                response = PlainTextResponse("Internal Server Error", status_code=500)
                await response(scope, receive, send_with_trace_id)
            raise
        finally:
            reset_trace_id(token)


def _incoming_trace_id(scope: Scope) -> str | None:
    values = [
        value
        for name, value in scope["headers"]
        if name.lower() == _TRACE_ID_HEADER_BYTES
    ]
    if len(values) != 1:
        return None
    return values[0].decode("latin-1")
