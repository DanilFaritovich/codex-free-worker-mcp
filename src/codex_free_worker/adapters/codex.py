from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from codex_free_worker.contracts import (
    ReasoningEffort,
    WorkerMode,
    WorkerRequest,
    WorkerResult,
    worker_result_json_schema,
)
from codex_free_worker.errors import WorkerExecutionError
from codex_free_worker.prompt import build_worker_prompt


class CodexAdapter:
    def __init__(
        self,
        *,
        codex_bin: str,
        model: str,
        reasoning_effort: ReasoningEffort,
        timeout_seconds: int,
        max_result_chars: int,
    ) -> None:
        self._codex_bin = codex_bin
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout_seconds = timeout_seconds
        self._max_result_chars = max_result_chars

    def execute(self, request: WorkerRequest) -> WorkerResult:
        sandbox = "read-only" if request.mode is WorkerMode.INSPECT else "workspace-write"
        prompt = build_worker_prompt(request.task, request.mode)

        with tempfile.TemporaryDirectory(prefix="codex-worker-") as temp_dir:
            schema_path = Path(temp_dir) / "worker-result.schema.json"
            schema_path.write_text(
                json.dumps(worker_result_json_schema(), ensure_ascii=False),
                encoding="utf-8",
            )

            command = [
                self._codex_bin,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--model",
                self._model,
                "--sandbox",
                sandbox,
                "--cd",
                str(request.cwd),
                "--output-schema",
                str(schema_path),
                "--color",
                "never",
                "--config",
                f'model_reasoning_effort="{self._reasoning_effort.value}"',
                "--config",
                'approval_policy="never"',
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
                )
            except FileNotFoundError as exc:
                raise WorkerExecutionError(
                    f"Codex executable not found: {self._codex_bin}"
                ) from exc

            try:
                stdout, _ = process.communicate(timeout=self._timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise WorkerExecutionError(
                    f"Codex worker exceeded {self._timeout_seconds}s timeout."
                ) from exc

            if process.returncode != 0:
                raise WorkerExecutionError(
                    f"Codex exited with code {process.returncode}; raw logs were not returned."
                )

        payload = stdout.strip()
        if not payload:
            raise WorkerExecutionError("Codex finished without a structured result.")
        if len(payload) > self._max_result_chars:
            raise WorkerExecutionError(
                f"Worker result exceeded {self._max_result_chars} characters; "
                "raw logs were not returned."
            )

        try:
            return WorkerResult.model_validate_json(payload)
        except Exception as exc:
            raise WorkerExecutionError("Codex returned an invalid structured result.") from exc
