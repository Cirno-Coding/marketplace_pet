import asyncio
import logging
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.types import Message

from src.application.tracing import current_trace_id
from src.infrastructure.logging_setup import TraceIdFilter
from src.presentation.api.middleware import TraceIdMiddleware

logger = logging.getLogger("tests.presentation.tracing")


def assert_uuid4(value: str) -> None:
    assert uuid.UUID(value).version == 4


@pytest.fixture
async def probe_client() -> AsyncClient:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)

    @app.get("/probe")
    async def probe(delay: float = 0) -> dict[str, str | None]:
        await asyncio.sleep(delay)
        logger.info("probe handled")
        return {"trace_id": current_trace_id()}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_missing_header_generates_uuid4(client: AsyncClient) -> None:
    resp = await client.get("/internal/users/1")

    assert_uuid4(resp.headers["X-Trace-Id"])


async def test_valid_header_is_echoed(client: AsyncClient) -> None:
    resp = await client.get(
        "/internal/users/1",
        headers={"X-Trace-Id": "0f8fad5b-d9cb-469f-a165-70867728950e"},
    )

    assert resp.status_code == 404
    assert resp.headers["X-Trace-Id"] == "0f8fad5b-d9cb-469f-a165-70867728950e"


async def test_header_name_is_case_insensitive(client: AsyncClient) -> None:
    resp = await client.get("/internal/users/1", headers={"x-trace-id": "abc:1.2_3"})

    assert resp.headers["X-Trace-Id"] == "abc:1.2_3"


@pytest.mark.parametrize(
    "value",
    ["", "has space", "a" * 129, "semi;colon", "трейс".encode()],
)
async def test_invalid_header_is_replaced(
    client: AsyncClient, value: str | bytes
) -> None:
    resp = await client.get("/internal/users/1", headers={"X-Trace-Id": value})

    returned = resp.headers["X-Trace-Id"]
    assert returned != value
    assert_uuid4(returned)


async def test_duplicate_headers_are_replaced(client: AsyncClient) -> None:
    resp = await client.get(
        "/internal/users/1",
        headers=[("X-Trace-Id", "first"), ("X-Trace-Id", "second")],
    )

    assert_uuid4(resp.headers["X-Trace-Id"])


async def test_control_characters_do_not_reach_context() -> None:
    seen: list[str | None] = []
    sent: list[Message] = []

    async def app(scope, receive, send) -> None:
        seen.append(current_trace_id())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {"type": "http", "headers": [(b"x-trace-id", b"abc\r\nINJECTED log line")]}
    await TraceIdMiddleware(app)(scope, receive, send)

    assert_uuid4(seen[0])
    assert (b"x-trace-id", seen[0].encode()) in sent[0]["headers"]


async def test_handler_sees_request_trace_id(probe_client: AsyncClient) -> None:
    resp = await probe_client.get("/probe", headers={"X-Trace-Id": "trace-handler"})

    assert resp.json() == {"trace_id": "trace-handler"}


async def test_generated_trace_id_matches_handler_and_response(
    probe_client: AsyncClient,
) -> None:
    resp = await probe_client.get("/probe")

    assert resp.json()["trace_id"] == resp.headers["X-Trace-Id"]


async def test_context_is_reset_after_request(probe_client: AsyncClient) -> None:
    await probe_client.get("/probe", headers={"X-Trace-Id": "trace-leak"})

    assert current_trace_id() is None


async def test_concurrent_requests_do_not_share_trace_id(
    probe_client: AsyncClient,
) -> None:
    slow, fast = await asyncio.gather(
        probe_client.get(
            "/probe", params={"delay": 0.05}, headers={"X-Trace-Id": "slow"}
        ),
        probe_client.get("/probe", headers={"X-Trace-Id": "fast"}),
    )

    assert slow.json() == {"trace_id": "slow"}
    assert fast.json() == {"trace_id": "fast"}


async def test_handler_logs_contain_trace_id(
    probe_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.handler.addFilter(TraceIdFilter())
    caplog.set_level(logging.INFO, logger=logger.name)

    await probe_client.get("/probe", headers={"X-Trace-Id": "trace-log"})

    records = [r for r in caplog.records if r.getMessage() == "probe handled"]
    assert [r.trace_id for r in records] == ["trace-log"]
