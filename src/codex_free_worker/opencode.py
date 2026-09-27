from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from codex_free_worker.config import Settings
from codex_free_worker.models import WorkerMode, WorkerResult
from codex_free_worker.prompt import build_worker_prompt, result_markers


class WorkerExecutionError(RuntimeError):
    pass


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _extract_marked_payload(stdout: str) -> str:
    start_marker, end_marker = result_markers()
    structured_candidates: list[str] = []

    # OpenCode --format json emits JSONL events.
    # Prefer strings extracted from already-decoded events so JSON escaping
    # from the transport layer never leaks into the result payload.
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            structured_candidates.append(line)
            continue

        structured_candidates.extend(_walk_strings(event))

    def extract(text: str) -> str | None:
        start = text.rfind(start_marker)
        if start < 0:
            return None

        start += len(start_marker)
        end = text.find(end_marker, start)
        if end < 0:
            return None

        return text[start:end].strip()

    # Prefer the latest decoded OpenCode event.
    for text in reversed(structured_candidates):
        payload = extract(text)
        if payload is not None:
            return payload

    # Compatibility fallback for non-JSON/plain-text OpenCode output.
    payload = extract(stdout)
    if payload is not None:
        return payload

    raise WorkerExecutionError("OpenCode finished without a marked compact result.")


def _parse_result(stdout: str, max_result_chars: int) -> WorkerResult:
    payload = _extract_marked_payload(stdout)
    if len(payload) > max_result_chars:
        raise WorkerExecutionError(
            f"Worker result exceeded {max_result_chars} characters; raw logs were not returned."
        )

    try:
        return WorkerResult.model_validate_json(payload)
    except Exception as exc:
        raise WorkerExecutionError("Worker returned an invalid compact JSON result.") from exc


def run_opencode_task(
    *,
    task: str,
    cwd: Path,
    mode: WorkerMode,
    settings: Settings,
) -> WorkerResult:
    if not cwd.is_absolute():
        raise ValueError("cwd must be an absolute path")
    if not cwd.is_dir():
        raise ValueError(f"cwd is not a directory: {cwd}")

    prompt = build_worker_prompt(task, mode)
    command = [
        settings.opencode_bin,
        "run",
        "--standalone",
        "--dir",
        str(cwd),
        "--model",
        settings.model,
        "--format",
        "json",
        prompt,
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise WorkerExecutionError(
            f"OpenCode executable not found: {settings.opencode_bin}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkerExecutionError(
            f"OpenCode worker exceeded {settings.timeout_seconds}s timeout."
        ) from exc

    # Deliberately never forward completed.stdout/stderr to the MCP caller.
    try:
        return _parse_result(completed.stdout, settings.max_result_chars)
    except WorkerExecutionError:
        if completed.returncode != 0:
            raise WorkerExecutionError(
                f"OpenCode exited with code {completed.returncode} without a valid compact result."
            ) from None
        raise
