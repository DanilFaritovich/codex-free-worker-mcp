from pathlib import Path

import pytest

from codex_free_worker.contracts import WorkerMode, WorkerRequest, WorkerResult, WorkerStatus
from codex_free_worker.service import WorkerService


class FakeExecutor:
    def __init__(self) -> None:
        self.requests: list[WorkerRequest] = []

    def execute(self, request: WorkerRequest) -> WorkerResult:
        self.requests.append(request)
        return WorkerResult(status=WorkerStatus.PASSED, summary="ok")


def test_service_resolves_and_forwards_allowed_cwd(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    executor = FakeExecutor()
    service = WorkerService(executor=executor, allowed_roots=(tmp_path,))

    result = service.execute(
        WorkerRequest(task="Inspect.", cwd=repo, mode=WorkerMode.INSPECT)
    )

    assert result.status is WorkerStatus.PASSED
    assert executor.requests[0].cwd == repo.resolve()


def test_service_rejects_cwd_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    executor = FakeExecutor()
    service = WorkerService(executor=executor, allowed_roots=(allowed,))

    with pytest.raises(ValueError, match="outside FREE_WORKER_ALLOWED_ROOTS"):
        service.execute(
            WorkerRequest(task="Inspect.", cwd=outside, mode=WorkerMode.INSPECT)
        )

    assert executor.requests == []


def test_service_rejects_missing_allowed_roots(tmp_path: Path) -> None:
    executor = FakeExecutor()
    service = WorkerService(executor=executor, allowed_roots=())

    with pytest.raises(ValueError, match="FREE_WORKER_ALLOWED_ROOTS"):
        service.execute(
            WorkerRequest(task="Inspect.", cwd=tmp_path, mode=WorkerMode.INSPECT)
        )

    assert executor.requests == []
