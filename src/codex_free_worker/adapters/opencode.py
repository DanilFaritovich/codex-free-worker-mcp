from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pydantic import TypeAdapter, ValidationError

from codex_free_worker.contracts import WorkerRequest, WorkerResult
from codex_free_worker.errors import InvalidWorkerReport, WorkerExecutionError
from codex_free_worker.project_env import build_project_env, resolve_backend_binary
from codex_free_worker.prompt import (
    build_opencode_prompt,
    build_report_repair_prompt,
    result_markers,
)

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
    allow_plain_json: bool = False

    def feed_line(self, line: str) -> None:
        text = _extract_text_event(line)
        if text is None:
            return

        payload = _extract_marked_payload(text)
        if payload is not None:
            self.latest_payload = payload
        elif self.allow_plain_json:
            self.latest_payload = text.strip()

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
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_context=False, include_url=False)
            # Only schema-defined top-level names and error codes are safe to expose.
            diagnostics = []
            for error in errors[:5]:
                location = error["loc"]
                field = location[0] if location else None
                name = field if field in WorkerResult.model_fields else "report"
                detail = f"{name}: {error['type']}"
                if error["type"] == "json_invalid":
                    position = re.search(r"line \d+ column \d+", error["msg"])
                    if position:
                        detail += f" ({position.group()})"
                diagnostics.append(detail)
            raise InvalidWorkerReport(
                payload,
                "; ".join(diagnostics),
                repairable=all(error["type"] != "value_error" for error in errors),
            ) from exc


def _validate_preserved_fields(payload: str, repaired: WorkerResult) -> None:
    """Reject changes to valid top-level values decoded before any syntax error."""
    decoder = json.JSONDecoder()
    position = len(payload) - len(payload.lstrip())
    if payload[position : position + 1] != "{":
        raise WorkerExecutionError("Report repair has no readable original object to preserve.")
    position += 1
    repaired_values = repaired.model_dump(mode="json")
    while position < len(payload):
        position += len(payload[position:]) - len(payload[position:].lstrip())
        if payload[position : position + 1] == "}":
            break
        try:
            key, position = decoder.raw_decode(payload, position)
            position += len(payload[position:]) - len(payload[position:].lstrip())
            if payload[position : position + 1] != ":":
                break
            position += 1
            position += len(payload[position:]) - len(payload[position:].lstrip())
            value, position = decoder.raw_decode(payload, position)
        except ValueError:
            break
        if isinstance(key, str) and key in WorkerResult.model_fields:
            annotation = WorkerResult.model_fields[key].annotation
            if annotation is None:
                raise WorkerExecutionError(f"Report field has no type annotation: {key}.")
            try:
                TypeAdapter(annotation).validate_python(value)
            except ValidationError:
                pass  # The field's structure is precisely what needs repair.
            else:
                if value != repaired_values[key]:
                    raise WorkerExecutionError(f"Report repair changed original field: {key}.")
        position += len(payload[position:]) - len(payload[position:].lstrip())
        if payload[position : position + 1] != ",":
            break
        position += 1


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
        report_retries: int = 1,
    ) -> None:
        if report_retries not in (0, 1):
            raise ValueError("report_retries must be 0 or 1")
        self._report_retries = report_retries
        self._opencode_bin = opencode_bin
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_result_chars = max_result_chars

    def execute(self, request: WorkerRequest) -> WorkerResult:
        deadline = time.monotonic() + self._timeout_seconds
        try:
            return self._run(
                build_opencode_prompt(request.task, request.mode),
                cwd=request.cwd,
                env=build_project_env(request.cwd),
                timeout_seconds=self._timeout_seconds,
                repair=False,
            )
        except InvalidWorkerReport as exc:
            if not self._report_retries or not exc.repairable:
                raise
            now = time.monotonic()
            repair_deadline = min(deadline, now + 60.0)
            remaining = repair_deadline - now
            if remaining <= 0:
                raise WorkerExecutionError("No worker time remains for report repair.") from None
            logger.warning(
                "Worker report requires format repair.",
                extra={"event": "report_repair_started", "backend": "opencode"},
            )
            try:
                with tempfile.TemporaryDirectory(prefix="worker-report-repair-") as temp_dir:
                    cwd = Path(temp_dir)
                    # Isolate project/global config, custom agents, tools and MCP servers.
                    # Provider authentication remains in the normal data directory.
                    config = {
                        "provider": self._repair_provider_config(request, min(10.0, remaining)),
                        "permission": {"*": "deny"},
                        "agent": {
                            "report-formatter": {
                                "mode": "primary",
                                "permission": {"*": "deny"},
                                "tools": {"*": False},
                            }
                        },
                    }
                    config_path = cwd / "opencode.json"
                    config_path.write_text(json.dumps(config), encoding="utf-8")
                    env = os.environ.copy()
                    env.update(
                        {
                            "XDG_CONFIG_HOME": temp_dir,
                            "OPENCODE_CONFIG_DIR": temp_dir,
                            "OPENCODE_CONFIG": str(config_path),
                            "OPENCODE_CONFIG_CONTENT": json.dumps(config),
                            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                        }
                    )
                    remaining = repair_deadline - time.monotonic()
                    if remaining <= 0:
                        raise WorkerExecutionError("No worker time remains for report repair.")
                    result = self._run(
                        build_report_repair_prompt(exc.payload, exc.diagnostic),
                        cwd=cwd,
                        env=env,
                        timeout_seconds=min(60.0, remaining),
                        repair=True,
                    )
                    _validate_preserved_fields(exc.payload, result)
            except WorkerExecutionError as repair_error:
                logger.warning(
                    "Worker report format repair failed.",
                    extra={"event": "report_repair_failed", "backend": "opencode"},
                )
                raise WorkerExecutionError(
                    f"Worker report repair failed after one attempt: {repair_error}"
                ) from None
            logger.info(
                "Worker report format repaired and validated.",
                extra={"event": "report_repair_completed", "backend": "opencode"},
            )
            return result

    def _repair_provider_config(
        self, request: WorkerRequest, timeout_seconds: float
    ) -> dict[str, object]:
        """Carry only the selected provider into the isolated formatter config."""
        try:
            completed = subprocess.run(
                [resolve_backend_binary(self._opencode_bin), "--pure", "debug", "config"],
                cwd=request.cwd,
                env=build_project_env(request.cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            raise WorkerExecutionError(
                "Could not inspect OpenCode provider configuration."
            ) from None
        if completed.returncode != 0:
            raise WorkerExecutionError("Could not inspect OpenCode provider configuration.")
        try:
            resolved = json.loads(completed.stdout)
            providers = resolved.get("provider", {})
            provider_id = self._model.split("/", 1)[0]
            selected = providers.get(provider_id)
            if selected is not None and not isinstance(selected, dict):
                raise ValueError("Invalid provider shape")
        except ValueError, AttributeError:
            raise WorkerExecutionError("Invalid OpenCode provider configuration.") from None
        return {provider_id: selected} if selected is not None else {}

    def _run(
        self,
        prompt: str,
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: float,
        repair: bool,
    ) -> WorkerResult:
        command = [
            resolve_backend_binary(self._opencode_bin),
            "run",
            *(["--pure", "--agent", "report-formatter"] if repair else ["--auto"]),
            "--dir",
            str(cwd),
            "--model",
            self._model,
            "--format",
            "json",
            prompt,
        ]

        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
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

        collector = _ResultCollector(allow_plain_json=repair)
        reader_errors: list[BaseException] = []
        reader = threading.Thread(
            target=_consume_stdout,
            args=(process.stdout, collector, reader_errors),
            daemon=True,
        )
        reader.start()

        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            reader.join(timeout=5)
            logger.warning(
                "Worker process exceeded timeout.",
                extra={
                    "event": "backend_timeout",
                    "backend": "opencode",
                    "timeout_seconds": timeout_seconds,
                },
            )
            raise WorkerExecutionError(
                f"OpenCode worker exceeded {timeout_seconds:g}s timeout."
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
