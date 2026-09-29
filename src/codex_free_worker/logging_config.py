"""Safe structured operation logging for the stdio MCP worker.

Only explicitly whitelisted fields are emitted. Never log task text, raw subprocess
stdout/stderr, credentials, full repository paths, or untrusted exception messages.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator

_request_id: ContextVar[str | None] = ContextVar("worker_request_id", default=None)
_HANDLER_NAME = "codex-free-worker-stderr"
_LOG_FIELDS = (
    "event",
    "backend",
    "mode",
    "status",
    "duration_ms",
    "changed_files_count",
    "check_count",
    "exit_code",
    "timeout_seconds",
    "error_type",
)


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def safe_stack(exc: BaseException) -> list[str]:
    """Keep actionable frame locations without leaking exception strings or paths."""
    if exc.__traceback__ is None:
        return []
    return [
        f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
        for frame in traceback.extract_tb(exc.__traceback__, limit=8)
    ]


class _SafeFormatter(logging.Formatter):
    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def _fields(self, record: logging.LogRecord) -> dict[str, object]:
        data: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "environment": self._environment,
        }
        request_id = _request_id.get()
        if request_id is not None:
            data["request_id"] = request_id

        for key in _LOG_FIELDS:
            value = getattr(record, key, None)
            if isinstance(value, (str, int, float, bool)):
                data[key] = value

        stack = getattr(record, "stack", None)
        if isinstance(stack, list) and all(isinstance(frame, str) for frame in stack):
            data["stack"] = stack

        return data


class JsonFormatter(_SafeFormatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self._fields(record), ensure_ascii=False, separators=(",", ":"))


class TextFormatter(_SafeFormatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = self._fields(record)
        return " ".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
        )


def configure_logging(
    *, level: str, log_format: str, service: str, environment: str
) -> None:
    """Configure package logs exactly once per call, always on stderr.

    Stdout is reserved for MCP protocol messages.
    """
    package_logger = logging.getLogger("codex_free_worker")
    package_logger.setLevel(level)
    package_logger.propagate = False

    for handler in tuple(package_logger.handlers):
        if handler.name == _HANDLER_NAME:
            package_logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    formatter_class = JsonFormatter if log_format == "json" else TextFormatter
    handler.setFormatter(formatter_class(service=service, environment=environment))
    package_logger.addHandler(handler)
