import uuid

import pytest

from src.application.tracing import (
    attach_trace_id,
    current_trace_id,
    exception_trace_id,
    new_trace_id,
    reset_trace_id,
    resolve_trace_id,
    set_trace_id,
)


def assert_uuid4(value: str) -> None:
    assert uuid.UUID(value).version == 4
    assert str(uuid.UUID(value)) == value


def test_current_trace_id_is_none_by_default() -> None:
    assert current_trace_id() is None


def test_set_and_reset_restore_previous_value() -> None:
    outer = set_trace_id("outer")
    inner = set_trace_id("inner")
    assert current_trace_id() == "inner"

    reset_trace_id(inner)
    assert current_trace_id() == "outer"

    reset_trace_id(outer)
    assert current_trace_id() is None


def test_new_trace_id_is_uuid4() -> None:
    assert_uuid4(new_trace_id())
    assert new_trace_id() != new_trace_id()


@pytest.mark.parametrize(
    "value",
    [
        "0f8fad5b-d9cb-469f-a165-70867728950e",
        "abc-123",
        "service.span_1:root",
        "a" * 128,
    ],
)
def test_resolve_keeps_valid_value(value: str) -> None:
    assert resolve_trace_id(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "a" * 129,
        "has space",
        "line\nbreak",
        "carriage\rreturn",
        "null\x00byte",
        "tab\tchar",
        "semi;colon",
        "slash/value",
        "трейс",
        "valid\n",
    ],
)
def test_resolve_replaces_missing_or_invalid_value(value: str | None) -> None:
    resolved = resolve_trace_id(value)

    assert resolved != value
    assert_uuid4(resolved)


def test_exception_has_no_trace_id_by_default() -> None:
    assert exception_trace_id(RuntimeError("x")) is None


def test_attach_trace_id_keeps_first_value() -> None:
    exc = RuntimeError("x")

    attach_trace_id(exc, "inner")
    attach_trace_id(exc, "outer")

    assert exception_trace_id(exc) == "inner"
