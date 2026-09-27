from __future__ import annotations

from pathlib import Path

from codex_free_worker.contracts import WorkerRequest, WorkerResult
from codex_free_worker.ports import WorkerExecutor


class WorkerService:
    def __init__(
        self,
        *,
        executor: WorkerExecutor,
        allowed_roots: tuple[Path, ...],
    ) -> None:
        self._executor = executor
        self._allowed_roots = allowed_roots

    def execute(self, request: WorkerRequest) -> WorkerResult:
        resolved_cwd = _resolve_cwd(request.cwd, self._allowed_roots)
        validated_request = request.model_copy(update={"cwd": resolved_cwd})
        return self._executor.execute(validated_request)


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
