import logging

from src.application.tracing import current_trace_id, exception_trace_id

LOG_FORMAT = "%(asctime)s %(levelname)s [trace_id=%(trace_id)s] %(name)s: %(message)s"

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        trace_id = current_trace_id() or _record_exception_trace_id(record)
        record.trace_id = trace_id or "-"
        return True


def _record_exception_trace_id(record: logging.LogRecord) -> str | None:
    if not record.exc_info or record.exc_info[1] is None:
        return None
    return exception_trace_id(record.exc_info[1])


class _TraceIdHandler(logging.StreamHandler):
    pass


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, _TraceIdHandler) for h in root.handlers):
        handler = _TraceIdHandler()
        handler.addFilter(TraceIdFilter())
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
