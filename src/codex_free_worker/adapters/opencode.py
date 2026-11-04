from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
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
)

logger = logging.getLogger(__name__)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerExecutionError("OpenCode final JSON contains ambiguous duplicate keys.")
        result[key] = value
    return result


@dataclass(slots=True)
class _ResultCollector:
    """Collect the last assistant step, never a report found in arbitrary output.

    OpenCode run.ts emits completed text parts and assistant processor step parts,
    but omits message.updated (and thus role/finish). A matching step_finish with
    reason=stop is the JSONL completion signal. See docs/opencode-results.md.
    """

    max_result_chars: int
    session_id: str | None = None
    message_id: str | None = None
    text: str = ""
    completed: bool = False
    has_tool: bool = False
    final_count: int = 0
    error: str | None = None

    def feed_line(self, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "error":
            self.error = "OpenCode reported a session error; no result was accepted."
            return
        part = event.get("part")
        if not isinstance(part, dict) or part.get("synthetic") is True:
            return
        if kind not in ("step_start", "step_finish", "text", "tool_use"):
            return
        expected_type = {
            "step_start": "step-start",
            "step_finish": "step-finish",
            "text": "text",
            "tool_use": "tool",
        }[kind]
        if part.get("type") != expected_type:
            return
        session = event.get("sessionID")
        message = part.get("messageID")
        if (
            not isinstance(session, str)
            or not session
            or part.get("sessionID") != session
            or not isinstance(message, str)
            or not message
        ):
            self.error = "OpenCode result events lack consistent session/message identifiers."
            return
        if self.session_id is not None and session != self.session_id:
            self.error = "OpenCode result contains ambiguous sessions."
            return
        if kind == "step_start":
            self.session_id = session
            self.message_id = message
            self.text = ""
            self.completed = False
            self.has_tool = False
            return
        if self.message_id != message or self.session_id != session or self.completed:
            self.error = "OpenCode result contains events outside an active assistant step."
            return
        if kind == "tool_use":
            self.has_tool = True
        elif kind == "text":
            timing = part.get("time")
            text = part.get("text")
            if not isinstance(timing, dict) or not timing.get("end") or not isinstance(text, str):
                self.error = "OpenCode assistant text is incomplete."
                return
            # Bound retained text even when the model ignores the compact report rule.
            self.text = (self.text + text[: self.max_result_chars + 1])[: self.max_result_chars + 1]
        elif kind == "step_finish":
            self.completed = part.get("reason") == "stop" and not self.has_tool
            if self.completed:
                self.final_count += 1
            else:
                self.text = ""
                self.message_id = None

    def build_result(self, max_result_chars: int) -> WorkerResult:
        if self.error:
            raise WorkerExecutionError(self.error)
        if self.final_count > 1:
            raise WorkerExecutionError("OpenCode returned multiple final assistant answers.")
        if not self.completed:
            raise WorkerExecutionError(
                "OpenCode finished without a completed final assistant answer."
            )
        payload = self.text
        if not payload.strip():
            raise WorkerExecutionError("OpenCode final assistant answer is empty.")
        if len(payload) > max_result_chars:
            raise WorkerExecutionError(
                f"Worker result exceeded {max_result_chars} characters; raw logs were not returned."
            )

        # Let schema validation produce its sanitized syntax diagnostic.
        with suppress(json.JSONDecodeError):
            json.loads(payload, object_pairs_hook=_unique_object)
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
    collector = _ResultCollector(max_result_chars)
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
            with self._task_environment(request) as env:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkerExecutionError("No worker time remains for task execution.")
                return self._run(
                    build_opencode_prompt(
                        request.task,
                        request.mode,
                        load_project_context=request.load_project_context,
                    ),
                    cwd=request.cwd,
                    env=env,
                    timeout_seconds=remaining,
                    repair=False,
                    load_project_context=request.load_project_context,
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
                        "provider": self._isolated_config(request, min(10.0, remaining))[
                            "provider"
                        ],
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
                            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "true",
                            "OPENCODE_DISABLE_CLAUDE_CODE": "true",
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

    @contextmanager
    def _task_environment(self, request: WorkerRequest) -> Iterator[dict[str, str]]:
        env = build_project_env(request.cwd)
        if request.load_project_context:
            yield env
            return

        # Keep provider connectivity, but omit global/project instructions, skills,
        # custom agents, plugins and MCP servers from this child process.
        config = self._isolated_config(request, min(10.0, self._timeout_seconds))
        permission = config.get("permission", {})
        # Context reduction must not relax existing command/file permission rules.
        permissions = dict(permission) if isinstance(permission, dict) else {"*": permission}
        permissions["skill"] = "deny"
        config.update({"permission": permissions, "tools": {"skill": False}})
        with tempfile.TemporaryDirectory(prefix="worker-context-") as temp_dir:
            config_path = Path(temp_dir) / "opencode.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            env.update(
                {
                    "XDG_CONFIG_HOME": temp_dir,
                    "OPENCODE_CONFIG_DIR": temp_dir,
                    "OPENCODE_CONFIG": str(config_path),
                    "OPENCODE_CONFIG_CONTENT": json.dumps(config),
                    "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "true",
                    "OPENCODE_DISABLE_CLAUDE_CODE": "true",
                }
            )
            yield env

    def _isolated_config(self, request: WorkerRequest, timeout_seconds: float) -> dict[str, object]:
        """Keep the selected provider and permissions, without ambient context."""
        env = build_project_env(request.cwd)
        if not request.load_project_context:
            env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "true"
            env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] = "true"
            env["OPENCODE_DISABLE_CLAUDE_CODE"] = "true"
        try:
            completed = subprocess.run(
                [resolve_backend_binary(self._opencode_bin), "--pure", "debug", "config"],
                cwd=request.cwd,
                env=env,
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
            permission = resolved.get("permission", {})
            if not isinstance(permission, (dict, str)):
                raise ValueError("Invalid permission shape")
        except ValueError, AttributeError:
            raise WorkerExecutionError("Invalid OpenCode provider configuration.") from None
        return {
            "provider": {provider_id: selected} if selected is not None else {},
            "permission": permission,
        }

    def _run(
        self,
        prompt: str,
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: float,
        repair: bool,
        load_project_context: bool = False,
    ) -> WorkerResult:
        command = [
            resolve_backend_binary(self._opencode_bin),
            "run",
            *(["--pure"] if repair or not load_project_context else []),
            *(["--agent", "report-formatter"] if repair else ["--auto"]),
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

        collector = _ResultCollector(self._max_result_chars)
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
                f"OpenCode exited with code {returncode}; no result was accepted."
            )
        return collector.build_result(self._max_result_chars)
