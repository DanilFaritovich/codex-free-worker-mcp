from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from codex_free_worker.contracts import (
    CodexWorkerResult,
    ReasoningEffort,
    SandboxMode,
    WorkerMode,
    WorkerRequest,
    WorkerResult,
    worker_result_json_schema,
)
from codex_free_worker.errors import WorkerExecutionError
from codex_free_worker.project_env import build_project_env, resolve_backend_binary
from codex_free_worker.prompt import build_worker_prompt

logger = logging.getLogger(__name__)


class CodexAdapter:
    def __init__(
        self,
        *,
        codex_bin: str,
        model: str,
        reasoning_effort: ReasoningEffort,
        inspect_sandbox: SandboxMode,
        fix_sandbox: SandboxMode,
        inspect_network: bool,
        fix_network: bool,
        timeout_seconds: int,
        max_result_chars: int,
    ) -> None:
        self._codex_bin = codex_bin
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._inspect_sandbox = inspect_sandbox
        self._fix_sandbox = fix_sandbox
        self._inspect_network = inspect_network
        self._fix_network = fix_network
        self._timeout_seconds = timeout_seconds
        self._max_result_chars = max_result_chars

    def execute(self, request: WorkerRequest) -> WorkerResult:
        sandbox_mode = (
            self._inspect_sandbox if request.mode is WorkerMode.INSPECT else self._fix_sandbox
        )
        sandbox = sandbox_mode.value
        network_enabled = (
            self._inspect_network if request.mode is WorkerMode.INSPECT else self._fix_network
        )
        prompt = build_worker_prompt(request.task, request.mode)

        with tempfile.TemporaryDirectory(prefix="codex-worker-") as temp_dir:
            schema_path = Path(temp_dir) / "worker-result.schema.json"
            schema_path.write_text(
                json.dumps(worker_result_json_schema(), ensure_ascii=False),
                encoding="utf-8",
            )

            command = [
                resolve_backend_binary(self._codex_bin),
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
            ]
            if network_enabled and sandbox_mode is SandboxMode.WORKSPACE_WRITE:
                command.extend(
                    [
                        "--config",
                        "sandbox_workspace_write.network_access=true",
                    ]
                )
            command.append(prompt)

            try:
                process = subprocess.Popen(
                    command,
                    cwd=request.cwd,
                    env=build_project_env(request.cwd),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            except FileNotFoundError as exc:
                logger.error(
                    "Worker executable not found.",
                    extra={"event": "backend_executable_missing", "backend": "codex"},
                )
                raise WorkerExecutionError(
                    f"Codex executable not found: {self._codex_bin}"
                ) from exc

            try:
                stdout, _ = process.communicate(timeout=self._timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                logger.warning(
                    "Worker process exceeded timeout.",
                    extra={
                        "event": "backend_timeout",
                        "backend": "codex",
                        "timeout_seconds": self._timeout_seconds,
                    },
                )
                raise WorkerExecutionError(
                    f"Codex worker exceeded {self._timeout_seconds}s timeout."
                ) from exc

            if process.returncode != 0:
                logger.error(
                    "Worker process exited unsuccessfully.",
                    extra={
                        "event": "backend_process_failed",
                        "backend": "codex",
                        "exit_code": process.returncode,
                    },
                )
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
            return CodexWorkerResult.model_validate_json(payload).to_worker_result()
        except Exception as exc:
            raise WorkerExecutionError("Codex returned an invalid structured result.") from exc
