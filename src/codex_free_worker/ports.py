from __future__ import annotations

from typing import Protocol, runtime_checkable

from codex_free_worker.contracts import WorkerRequest, WorkerResult


@runtime_checkable
class WorkerExecutor(Protocol):
    def execute(self, request: WorkerRequest) -> WorkerResult:
        """Execute one validated worker request."""
        ...
