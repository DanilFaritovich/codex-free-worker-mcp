from __future__ import annotations

import json
import logging
import subprocess
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TextIO

from codex_free_worker.contracts import WorkerRequest, WorkerResult
from codex_free_worker.errors import WorkerExecutionError
from codex_free_worker.prompt import build_opencode_prompt, result_markers

logger = logging.getLogger(__name__)


def _extract_marked_payload(text: str) -> str | None:
    start_marker, end_marker = result_markers()
    start = text.rfind(start_marker)
    if start < 0:
        return None

    start += len(start_marker)
    end = text.find(end_marker, start)
    if end < 0:
        return None

    return text[start:end].strip()


def _extract_text_event(line: str) -> str | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(event, dict) or event.get("type") != "text":
        return None

    part = event.get("part")
    if not isinstance(part, dict) or part.get("type") != "text":
        return None
    if part.get("synthetic") is True:
        return None

    text = part.get("text")
    return text if isinstance(text, str) else None


@dataclass(slots=True)
class _ResultCollector:
    latest_payload: str | None = None

    def feed_line(self, line: str) -> None:
        text = _extract_text_event(line)
        if text is None:
            return

        payload = _extract_marked_payload(text)
        if payload is not None:
            self.latest_payload = payload

    def build_result(self, max_result_chars: int) -> WorkerResult:
        payload = self.latest_payload
        if payload is None:
            raise WorkerExecutionError("OpenCode finished without a marked compact result.")
        if len(payload) > max_result_chars:
            raise WorkerExecutionError(
                f"Worker result exceeded {max_result_chars} characters; raw logs were not returned."
            )

        try:
            return WorkerResult.model_validate_json(payload)
        except Exception as exc:
            raise WorkerExecutionError("Worker returned an invalid compact JSON result.") from exc


def _parse_result_lines(lines: Iterable[str], max_result_chars: int) -> WorkerResult:
    collector = _ResultCollector()
    for line in lines:
        collector.feed_line(line)
    return collector.build_result(max_result_chars)


def _parse_result(stdout: str, max_result_chars: int) -> WorkerResult:
    return _parse_result_lines(stdout.splitlines(), max_result_chars)


def _consume_stdout(
    stream: TextIO,
    collector: _ResultCollector,
    errors: list[BaseException],
) -> None:
    try:
        for line in stream:
            collector.feed_line(line)
    except BaseException as exc:  # pragma: no cover - defensive stream failure
        errors.append(exc)


class OpenCodeAdapter:
    def __init__(
        self,
        *,
        opencode_bin: str,
        model: str,
        timeout_seconds: int,
        max_result_chars: int,
    ) -> None:
        self._opencode_bin = opencode_bin
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_result_chars = max_result_chars

    def execute(self, request: WorkerRequest) -> WorkerResult:
        prompt = build_opencode_prompt(request.task, request.mode)
        command = [
            self._opencode_bin,
            "run",
            "--auto",
            "--dir",
            str(request.cwd),
            "--model",
            self._model,
            "--format",
            "json",
            prompt,
        ]

        try:
            process = subprocess.Popen(
                command,
                cwd=request.cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            logger.error(
                "Worker executable not found.",
                extra={"event": "backend_executable_missing", "backend": "opencode"},
            )
            raise WorkerExecutionError(
                f"OpenCode executable not found: {self._opencode_bin}"
            ) from exc

        if process.stdout is None:  # pragma: no cover - PIPE guarantees stdout
            process.kill()
            raise WorkerExecutionError("OpenCode stdout pipe was not created.")

        collector = _ResultCollector()
        reader_errors: list[BaseException] = []
        reader = threading.Thread(
            target=_consume_stdout,
            args=(process.stdout, collector, reader_errors),
            daemon=True,
        )
        reader.start()

        try:
            returncode = process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            reader.join(timeout=5)
            logger.warning(
                "Worker process exceeded timeout.",
                extra={
                    "event": "backend_timeout",
                    "backend": "opencode",
                    "timeout_seconds": self._timeout_seconds,
                },
            )
            raise WorkerExecutionError(
                f"OpenCode worker exceeded {self._timeout_seconds}s timeout."
            ) from exc

        reader.join(timeout=5)
        if reader.is_alive():
            process.kill()
            raise WorkerExecutionError("OpenCode stdout reader did not terminate.")
        if reader_errors:
            raise WorkerExecutionError("Failed while reading OpenCode JSONL output.")

        try:
            return collector.build_result(self._max_result_chars)
        except WorkerExecutionError:
            if returncode != 0:
                logger.error(
                    "Worker process exited unsuccessfully.",
                    extra={
                        "event": "backend_process_failed",
                        "backend": "opencode",
                        "exit_code": returncode,
                    },
                )
                raise WorkerExecutionError(
                    f"OpenCode exited with code {returncode} without a valid compact result."
                ) from None
            raise
