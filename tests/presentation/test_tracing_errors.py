import logging
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send

from src.application.tracing import current_trace_id, exception_trace_id
from src.infrastructure.logging_setup import TraceIdFilter
from src.presentation.api.middleware import TraceIdMiddleware


class BoomError(RuntimeError):
    pass


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)

    @app.get("/boom")
    async def boom() -> None:
        raise BoomError("boom")

    return app


def make_scope(trace_id: str | None = None) -> Scope:
    headers = [] if trace_id is None else [(b"x-trace-id", trace_id.encode())]
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/boom",
        "raw_path": b"/boom",
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }


async def receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


class RecordingSend:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.trace_ids_at_start: list[str | None] = []

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.trace_ids_at_start.append(current_trace_id())
        self.messages.append(message)

    def starts(self) -> list[Message]:
        return [m for m in self.messages if m["type"] == "http.response.start"]


async def test_500_response_has_request_trace_id() -> None:
    transport = ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/boom", headers={"X-Trace-Id": "trace-500"})

    assert resp.status_code == 500
    assert resp.text == "Internal Server Error"
    assert resp.headers["X-Trace-Id"] == "trace-500"


async def test_500_response_has_generated_trace_id() -> None:
    transport = ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/boom")

    assert resp.status_code == 500
    assert uuid.UUID(resp.headers["X-Trace-Id"]).version == 4


async def test_500_is_sent_once_inside_request_context() -> None:
    send = RecordingSend()

    with pytest.raises(BoomError):
        await make_app()(make_scope("trace-ctx"), receive, send)

    [start] = send.starts()
    assert start["status"] == 500
    assert send.trace_ids_at_start == ["trace-ctx"]
    assert current_trace_id() is None


async def test_exception_reaching_server_carries_trace_id() -> None:
    with pytest.raises(BoomError) as exc_info:
        await make_app()(make_scope("trace-exc"), receive, RecordingSend())

    assert exception_trace_id(exc_info.value) == "trace-exc"


async def test_error_after_response_started_is_not_answered_twice() -> None:
    async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise BoomError("stream broke")

    send = RecordingSend()

    with pytest.raises(BoomError) as exc_info:
        await TraceIdMiddleware(streaming_app)(
            make_scope("trace-stream"), receive, send
        )

    assert [m["status"] for m in send.starts()] == [200]
    assert exception_trace_id(exc_info.value) == "trace-stream"
    assert current_trace_id() is None


async def test_server_error_log_after_request_has_trace_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.handler.addFilter(TraceIdFilter())
    server_logger = logging.getLogger("uvicorn.error")

    try:
        await make_app()(make_scope("trace-log"), receive, RecordingSend())
    except BoomError as exc:
        assert current_trace_id() is None
        server_logger.error("Exception in ASGI application\n", exc_info=exc)

    [record] = [r for r in caplog.records if r.name == "uvicorn.error"]
    assert record.trace_id == "trace-log"
