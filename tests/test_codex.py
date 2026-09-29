from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from codex_free_worker.adapters.codex import CodexAdapter
from codex_free_worker.contracts import (
    ReasoningEffort,
    SandboxMode,
    WorkerMode,
    WorkerRequest,
    WorkerStatus,
)
from codex_free_worker.errors import WorkerExecutionError


def _payload() -> str:
    return json.dumps(
        {
            "status": "passed",
            "summary": "Checks passed.",
            "changed_files": [],
            "checks": [{"name": "make check", "result": "passed"}],
            "relevant_locations": [],
            "needs_main_model_decision": False,
            "decision_required": None,
        }
    )


class _FakeProcess:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self._stdout = stdout
        self.returncode = returncode
        self.killed = False

    def communicate(self, timeout: int | None = None) -> tuple[str, None]:
        del timeout
        return self._stdout, None

    def kill(self) -> None:
        self.killed = True


def _adapter(
    *,
    inspect_sandbox: SandboxMode = SandboxMode.WORKSPACE_WRITE,
    fix_sandbox: SandboxMode = SandboxMode.WORKSPACE_WRITE,
) -> CodexAdapter:
    return CodexAdapter(
        codex_bin="codex",
        model="gpt-6-luna",
        reasoning_effort=ReasoningEffort.LOW,
        inspect_sandbox=inspect_sandbox,
        fix_sandbox=fix_sandbox,
        timeout_seconds=30,
        max_result_chars=8_000,
    )


@pytest.mark.parametrize(
    ("mode", "inspect_sandbox", "fix_sandbox", "expected_sandbox"),
    [
        (
            WorkerMode.INSPECT,
            SandboxMode.WORKSPACE_WRITE,
            SandboxMode.WORKSPACE_WRITE,
            "workspace-write",
        ),
        (
            WorkerMode.FIX,
            SandboxMode.WORKSPACE_WRITE,
            SandboxMode.WORKSPACE_WRITE,
            "workspace-write",
        ),
        (
            WorkerMode.INSPECT,
            SandboxMode.READ_ONLY,
            SandboxMode.WORKSPACE_WRITE,
            "read-only",
        ),
        (
            WorkerMode.FIX,
            SandboxMode.WORKSPACE_WRITE,
            SandboxMode.READ_ONLY,
            "read-only",
        ),
    ],
)
def test_codex_command_is_isolated_and_uses_mode_sandbox(
    tmp_path: Path,
    mode: WorkerMode,
    inspect_sandbox: SandboxMode,
    fix_sandbox: SandboxMode,
    expected_sandbox: str,
) -> None:
    process = _FakeProcess(_payload())
    captured_commands: list[list[str]] = []
    captured_schemas: list[dict[str, object]] = []

    def popen(command: list[str], **kwargs: object) -> _FakeProcess:
        captured_commands.append(command)
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured_schemas.append(json.loads(schema_path.read_text(encoding="utf-8")))
        assert kwargs["stderr"] is subprocess.DEVNULL
        return process

    with patch("codex_free_worker.adapters.codex.subprocess.Popen", side_effect=popen):
        result = _adapter(
            inspect_sandbox=inspect_sandbox,
            fix_sandbox=fix_sandbox,
        ).execute(WorkerRequest(task="Run make check.", cwd=tmp_path, mode=mode))

    command = captured_commands[0]
    schema = captured_schemas[0]
    assert Path(command[0]).name == "codex"
    assert command[1] == "exec"
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert command[command.index("--model") + 1] == "gpt-6-luna"
    assert command[command.index("--sandbox") + 1] == expected_sandbox
    assert command[command.index("--cd") + 1] == str(tmp_path)
    assert 'model_reasoning_effort="low"' in command
    assert 'approval_policy="never"' in command
    assert schema["additionalProperties"] is False
    assert result.status is WorkerStatus.PASSED
    assert result.checks == {"make check": "passed"}


def test_codex_rejects_invalid_structured_result(tmp_path: Path) -> None:
    with (
        patch(
            "codex_free_worker.adapters.codex.subprocess.Popen",
            return_value=_FakeProcess("not-json"),
        ),
        pytest.raises(WorkerExecutionError, match="invalid structured result"),
    ):
        _adapter().execute(
            WorkerRequest(
                task="Run make check.",
                cwd=tmp_path,
                mode=WorkerMode.INSPECT,
            )
        )


def test_codex_nonzero_exit_does_not_forward_raw_logs(tmp_path: Path) -> None:
    with (
        patch(
            "codex_free_worker.adapters.codex.subprocess.Popen",
            return_value=_FakeProcess("SECRET RAW OUTPUT", returncode=2),
        ),
        pytest.raises(WorkerExecutionError) as exc_info,
    ):
        _adapter().execute(
            WorkerRequest(
                task="Run make check.",
                cwd=tmp_path,
                mode=WorkerMode.INSPECT,
            )
        )

    assert "SECRET RAW OUTPUT" not in str(exc_info.value)


def test_codex_missing_binary_is_reported(tmp_path: Path) -> None:
    with (
        patch(
            "codex_free_worker.adapters.codex.subprocess.Popen",
            side_effect=FileNotFoundError,
        ),
        pytest.raises(WorkerExecutionError, match="Codex executable not found"),
    ):
        _adapter().execute(
            WorkerRequest(
                task="Run make check.",
                cwd=tmp_path,
                mode=WorkerMode.INSPECT,
            )
        )


def test_codex_timeout_is_reported(tmp_path: Path) -> None:
    class TimeoutProcess(_FakeProcess):
        def __init__(self) -> None:
            super().__init__()
            self._timed_out = False

        def communicate(self, timeout: int | None = None) -> tuple[str, None]:
            if not self._timed_out:
                self._timed_out = True
                raise subprocess.TimeoutExpired(cmd="codex", timeout=timeout or 0)
            return "", None

    process = TimeoutProcess()
    with (
        patch(
            "codex_free_worker.adapters.codex.subprocess.Popen",
            return_value=process,
        ),
        pytest.raises(WorkerExecutionError, match="exceeded 30s timeout"),
    ):
        _adapter().execute(
            WorkerRequest(
                task="Run make check.",
                cwd=tmp_path,
                mode=WorkerMode.INSPECT,
            )
        )

    assert process.killed is True


def test_codex_subprocess_inherits_target_project_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_bin = tmp_path / ".venv" / "bin"
    project_bin.mkdir(parents=True)
    monkeypatch.setenv("PATH", "/parent/bin")
    monkeypatch.setenv("VIRTUAL_ENV", "/parent/venv")

    with patch(
        "codex_free_worker.adapters.codex.subprocess.Popen",
        return_value=_FakeProcess(_payload()),
    ) as popen:
        _adapter().execute(
            WorkerRequest(task="Run make check.", cwd=tmp_path, mode=WorkerMode.INSPECT)
        )

    child_env = popen.call_args.kwargs["env"]
    assert child_env["PATH"] == f"{project_bin}{os.pathsep}/parent/bin"
    assert child_env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    assert os.environ["PATH"] == "/parent/bin"
    assert os.environ["VIRTUAL_ENV"] == "/parent/venv"
