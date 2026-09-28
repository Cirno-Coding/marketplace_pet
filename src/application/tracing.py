import re
import uuid
from contextvars import ContextVar, Token

TRACE_ID_HEADER = "X-Trace-Id"

_TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")

_EXCEPTION_ATTR = "__trace_id__"

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def current_trace_id() -> str | None:
    return _trace_id.get()


def set_trace_id(value: str) -> Token[str | None]:
    return _trace_id.set(value)


def reset_trace_id(token: Token[str | None]) -> None:
    _trace_id.reset(token)


def new_trace_id() -> str:
    return str(uuid.uuid4())


def resolve_trace_id(incoming: str | None) -> str:
    if incoming is not None and _TRACE_ID_PATTERN.fullmatch(incoming):
        return incoming
    return new_trace_id()


def attach_trace_id(exc: BaseException, trace_id: str) -> None:
    if exception_trace_id(exc) is None:
        setattr(exc, _EXCEPTION_ATTR, trace_id)


def exception_trace_id(exc: BaseException) -> str | None:
    return getattr(exc, _EXCEPTION_ATTR, None)
