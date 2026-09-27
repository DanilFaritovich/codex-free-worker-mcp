from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_free_worker.contracts import WorkerMode, WorkerRequest, WorkerResult, WorkerStatus


def test_worker_request_strips_task() -> None:
    request = WorkerRequest(task="  Run make check.  ", cwd=Path("/tmp/repo"), mode=WorkerMode.INSPECT)

    assert request.task == "Run make check."


def test_worker_request_rejects_empty_task() -> None:
    with pytest.raises(ValidationError, match="task"):
        WorkerRequest(task="   ", cwd=Path("/tmp/repo"), mode=WorkerMode.INSPECT)


def test_worker_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        WorkerResult(
            status=WorkerStatus.PASSED,
            summary="Checks passed.",
            unexpected=True,
        )
