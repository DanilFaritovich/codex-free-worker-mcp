from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from codex_free_worker.config import Settings
from codex_free_worker.models import WorkerMode, WorkerResult
from codex_free_worker.prompt import build_worker_prompt, result_markers


class WorkerExecutionError(RuntimeError):
    pass


def _resolve_cwd(cwd: Path, allowed_roots: tuple[Path, ...]) -> Path:
    if not cwd.is_absolute():
        raise ValueError("cwd must be an absolute path")

    try:
        resolved_cwd = cwd.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"cwd is not a directory: {cwd}") from exc

    if not resolved_cwd.is_dir():
        raise ValueError(f"cwd is not a directory: {cwd}")

    if not allowed_roots:
        raise ValueError(
            "FREE_WORKER_ALLOWED_ROOTS must contain at least one allowed repository root"
        )

    for root in allowed_roots:
        resolved_root = root.resolve()
        if resolved_cwd == resolved_root or resolved_cwd.is_relative_to(resolved_root):
            return resolved_cwd

    raise ValueError(f"cwd is outside FREE_WORKER_ALLOWED_ROOTS: {resolved_cwd}")


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


def run_opencode_task(
    *,
    task: str,
    cwd: Path,
    mode: WorkerMode,
    settings: Settings,
) -> WorkerResult:
    resolved_cwd = _resolve_cwd(cwd, settings.allowed_roots)

    prompt = build_worker_prompt(task, mode)
    command = [
        settings.opencode_bin,
        "run",
        "--auto",
        "--dir",
        str(resolved_cwd),
        "--model",
        settings.model,
        "--format",
        "json",
        prompt,
    ]

    try:
        process = subprocess.Popen(
            command,
            cwd=resolved_cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise WorkerExecutionError(
            f"OpenCode executable not found: {settings.opencode_bin}"
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
        returncode = process.wait(timeout=settings.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        reader.join(timeout=5)
        raise WorkerExecutionError(
            f"OpenCode worker exceeded {settings.timeout_seconds}s timeout."
        ) from exc

    reader.join(timeout=5)
    if reader.is_alive():
        process.kill()
        raise WorkerExecutionError("OpenCode stdout reader did not terminate.")
    if reader_errors:
        raise WorkerExecutionError("Failed while reading OpenCode JSONL output.")

    try:
        return collector.build_result(settings.max_result_chars)
    except WorkerExecutionError:
        if returncode != 0:
            raise WorkerExecutionError(
                f"OpenCode exited with code {returncode} without a valid compact result."
            ) from None
        raise
