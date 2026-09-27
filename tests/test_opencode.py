from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from codex_free_worker.config import Settings
from codex_free_worker.models import WorkerMode, WorkerStatus
from codex_free_worker.opencode import WorkerExecutionError, _parse_result, run_opencode_task


def _event(payload: dict[str, object]) -> str:
    text = f"noise\nFREE_WORKER_RESULT_BEGIN\n{json.dumps(payload)}\nFREE_WORKER_RESULT_END"
    return json.dumps({"type": "text", "part": {"text": text}})


def test_parse_result_drops_raw_logs() -> None:
    raw = "\n".join(
        [
            json.dumps({"type": "tool", "output": "VERY LARGE RAW TEST LOG"}),
            _event(
                {
                    "status": "failed",
                    "summary": "Ruff format failed in two files.",
                    "changed_files": [],
                    "checks": {"make check": "failed"},
                    "relevant_locations": ["backend/app/a.py:1"],
                    "needs_main_model_decision": False,
                    "decision_required": None,
                }
            ),
        ]
    )
    result = _parse_result(raw, 8_000)
    assert result.status is WorkerStatus.FAILED
    assert "VERY LARGE RAW TEST LOG" not in result.model_dump_json()


def test_missing_marker_is_rejected() -> None:
    with pytest.raises(WorkerExecutionError, match="marked compact result"):
        _parse_result(json.dumps({"text": "raw only"}), 8_000)


def test_run_uses_fixed_model_and_directory(tmp_path: Path) -> None:
    stdout = _event(
        {
            "status": "passed",
            "summary": "Checks passed.",
            "changed_files": [],
            "checks": {"make check": "passed"},
            "relevant_locations": [],
            "needs_main_model_decision": False,
            "decision_required": None,
        }
    )

    class Completed:
        returncode = 0
        stderr = "raw stderr"

        def __init__(self) -> None:
            self.stdout = stdout

    settings = Settings(timeout_seconds=30)
    with patch("codex_free_worker.opencode.subprocess.run", return_value=Completed()) as run:
        result = run_opencode_task(
            task="Run make check.",
            cwd=tmp_path,
            mode=WorkerMode.INSPECT,
            settings=settings,
        )

    command = run.call_args.args[0]
    assert command[:2] == ["opencode", "run"]
    assert "--auto" in command
    assert str(tmp_path) in command
    assert "openrouter/cohere/north-mini-code:free" in command
    assert result.status is WorkerStatus.PASSED
