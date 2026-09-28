import io
import logging
from collections.abc import Iterator

import pytest

from src.application.tracing import attach_trace_id, reset_trace_id, set_trace_id
from src.infrastructure.logging_setup import (
    LOG_FORMAT,
    TraceIdFilter,
    configure_logging,
)


def make_record() -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, "hello", None, None)


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_filter_adds_current_trace_id() -> None:
    record = make_record()
    token = set_trace_id("trace-1")
    try:
        assert TraceIdFilter().filter(record) is True
    finally:
        reset_trace_id(token)

    assert record.trace_id == "trace-1"


def test_filter_uses_dash_without_trace_id() -> None:
    record = make_record()

    TraceIdFilter().filter(record)

    assert record.trace_id == "-"


def test_formatted_line_contains_trace_id() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger = logging.getLogger("tests.logging_setup")
    logger.addHandler(handler)
    logger.propagate = False
    token = set_trace_id("trace-2")
    try:
        logger.warning("something happened")
    finally:
        reset_trace_id(token)
        logger.removeHandler(handler)
        logger.propagate = True

    assert (
        "[trace_id=trace-2] tests.logging_setup: something happened"
        in stream.getvalue()
    )


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    before = len(root.handlers)

    configure_logging()
    configure_logging()

    assert len(root.handlers) == before + 1
    added = root.handlers[-1]
    assert any(isinstance(f, TraceIdFilter) for f in added.filters)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True


def make_error_record(exc: BaseException) -> logging.LogRecord:
    return logging.LogRecord(
        "test", logging.ERROR, __file__, 1, "failed", None, (type(exc), exc, None)
    )


def test_filter_takes_trace_id_from_exception_outside_context() -> None:
    exc = RuntimeError("boom")
    attach_trace_id(exc, "trace-exc")
    record = make_error_record(exc)

    TraceIdFilter().filter(record)

    assert record.trace_id == "trace-exc"


def test_filter_prefers_current_context_over_exception() -> None:
    exc = RuntimeError("boom")
    attach_trace_id(exc, "trace-exc")
    record = make_error_record(exc)

    token = set_trace_id("trace-ctx")
    try:
        TraceIdFilter().filter(record)
    finally:
        reset_trace_id(token)

    assert record.trace_id == "trace-ctx"


def test_filter_uses_dash_for_exception_without_trace_id() -> None:
    record = make_error_record(RuntimeError("boom"))

    TraceIdFilter().filter(record)

    assert record.trace_id == "-"
