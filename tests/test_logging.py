from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from codex_free_worker import logging_config
from codex_free_worker.contracts import WorkerMode, WorkerResult, WorkerStatus
from codex_free_worker.server import _run_task


@pytest.fixture
def isolated_package_logger() -> Iterator[logging.Logger]:
    package_logger = logging.getLogger("codex_free_worker")
    old_handlers = package_logger.handlers[:]
    old_level = package_logger.level
    old_propagate = package_logger.propagate
    package_logger.handlers = []
    try:
        yield package_logger
    finally:
        for handler in package_logger.handlers:
            handler.close()
        package_logger.handlers = old_handlers
        package_logger.setLevel(old_level)
        package_logger.propagate = old_propagate


def _configure_json(stream: StringIO, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stderr", stream)
    logging_config.configure_logging(
        level="INFO",
        log_format="json",
        service="codex-free-worker",
        environment="test",
    )


def test_json_formatter_writes_safe_fields_only_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    isolated_package_logger: logging.Logger,
) -> None:
    stderr = StringIO()
    _configure_json(stderr, monkeypatch)
    logger = logging.getLogger("codex_free_worker.test")

    with logging_config.bind_request_id("safe-request-id"):
        logger.info(
            "Worker task completed.",
            extra={
                "event": "worker_completed",
                "backend": "codex",
                "mode": "fix",
                "status": "passed",
                "duration_ms": 123,
                "exit_code": 0,
                "prompt": "SECRET_PROMPT",
                "raw_stderr": "SECRET_ERROR_LOG",
                "api_key": "SECRET_API_KEY",
            },
        )

    payload = json.loads(stderr.getvalue())
    assert datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "codex_free_worker.test"
    assert payload["message"] == "Worker task completed."
    assert payload["service"] == "codex-free-worker"
    assert payload["environment"] == "test"
    assert payload["request_id"] == "safe-request-id"
    assert payload["event"] == "worker_completed"
    assert payload["backend"] == "codex"
    assert payload["mode"] == "fix"
    assert payload["duration_ms"] == 123
    assert payload["exit_code"] == 0
    assert "SECRET_" not in stderr.getvalue()
    assert "\n" not in stderr.getvalue().rstrip("\n")


def test_request_context_is_reset_after_task(
    monkeypatch: pytest.MonkeyPatch,
    isolated_package_logger: logging.Logger,
) -> None:
    stderr = StringIO()
    _configure_json(stderr, monkeypatch)
    logger = logging.getLogger("codex_free_worker.test")
    logger.info("Before.")
    with logging_config.bind_request_id("request-1"):
        logger.info("During.")
    logger.info("After.")

    records = [json.loads(line) for line in stderr.getvalue().splitlines()]
    assert "request_id" not in records[0]
    assert records[1]["request_id"] == "request-1"
    assert "request_id" not in records[2]


def test_reconfiguration_does_not_duplicate_handlers(
    monkeypatch: pytest.MonkeyPatch,
    isolated_package_logger: logging.Logger,
) -> None:
    stderr = StringIO()
    _configure_json(stderr, monkeypatch)
    _configure_json(stderr, monkeypatch)

    logging.getLogger("codex_free_worker.test").info("Only once.")
    assert len(stderr.getvalue().splitlines()) == 1
    assert isolated_package_logger.propagate is False


def test_human_format_also_uses_stderr(
    monkeypatch: pytest.MonkeyPatch,
    isolated_package_logger: logging.Logger,
) -> None:
    stderr = StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    logging_config.configure_logging(
        level="INFO", log_format="text", service="worker", environment="local"
    )

    logging.getLogger("codex_free_worker.test").info("Startup.", extra={"event": "server_starting"})
    output = stderr.getvalue()
    assert 'event="server_starting"' in output
    assert 'service="worker"' in output


def test_task_lifecycle_contains_bounded_structured_metadata(
    monkeypatch: pytest.MonkeyPatch,
    isolated_package_logger: logging.Logger,
    tmp_path: Path,
) -> None:
    stderr = StringIO()
    _configure_json(stderr, monkeypatch)
    monkeypatch.setenv("FREE_WORKER_BACKEND", "codex")

    passed = WorkerResult(status=WorkerStatus.PASSED, summary="SENSITIVE_RESULT")
    with patch("codex_free_worker.server.build_worker_service") as build:
        build.return_value.execute.return_value = passed
        result = _run_task("SENSITIVE_PROMPT", str(tmp_path), WorkerMode.INSPECT)

    assert result is passed
    records = [json.loads(line) for line in stderr.getvalue().splitlines()]
    assert [record["event"] for record in records] == ["worker_started", "worker_completed"]
    assert records[0]["request_id"] == records[1]["request_id"]
    assert records[0]["backend"] == "codex"
    assert records[1]["mode"] == "inspect"
    assert records[1]["status"] == "passed"
    assert records[1]["duration_ms"] >= 0
    assert records[1]["changed_files_count"] == 0
    assert records[1]["check_count"] == 0
    assert "SENSITIVE_" not in stderr.getvalue()
    assert str(tmp_path) not in stderr.getvalue()


def test_unexpected_exception_logs_safe_stack_but_not_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    isolated_package_logger: logging.Logger,
    tmp_path: Path,
) -> None:
    stderr = StringIO()
    _configure_json(stderr, monkeypatch)
    monkeypatch.setenv("FREE_WORKER_BACKEND", "codex")

    with patch("codex_free_worker.server.build_worker_service") as build:
        build.return_value.execute.side_effect = RuntimeError("SUPER_SECRET_CREDENTIAL")
        result = _run_task("SUPER_SECRET_TASK", str(tmp_path), WorkerMode.FIX)

    assert result.status is WorkerStatus.FAILED
    assert "SUPER_SECRET_" not in result.summary
    records = [json.loads(line) for line in stderr.getvalue().splitlines()]
    error_record = records[-1]
    assert error_record["event"] == "worker_failed"
    assert error_record["error_type"] == "RuntimeError"
    assert error_record["stack"]
    assert "SUPER_SECRET_" not in stderr.getvalue()
    assert str(tmp_path) not in stderr.getvalue()


def test_stdio_module_entrypoint_emits_json_to_stderr() -> None:
    """Exercise the real python -m entrypoint, not only an imported module."""
    process = subprocess.run(
        [sys.executable, "-m", "codex_free_worker.server", "stdio"],
        input="",
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env={
            **os.environ,
            "LOG_FORMAT": "json",
            "LOG_LEVEL": "INFO",
            "ENVIRONMENT": "test",
        },
    )

    assert process.returncode == 0
    records = [
        json.loads(line)
        for line in process.stderr.splitlines()
        if line.startswith("{")
    ]
    assert any(
        record.get("event") == "server_starting"
        and record.get("logger") == "codex_free_worker.server"
        and record.get("environment") == "test"
        for record in records
    )
    assert "MCP server starting." not in process.stdout
