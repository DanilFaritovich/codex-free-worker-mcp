from __future__ import annotations

from codex_free_worker.adapters.codex import CodexAdapter
from codex_free_worker.adapters.opencode import OpenCodeAdapter
from codex_free_worker.config import Settings
from codex_free_worker.contracts import WorkerBackend
from codex_free_worker.ports import WorkerExecutor
from codex_free_worker.service import WorkerService


def build_worker_executor(settings: Settings) -> WorkerExecutor:
    if settings.backend is WorkerBackend.CODEX:
        return CodexAdapter(
            codex_bin=settings.codex_bin,
            model=settings.codex_model,
            reasoning_effort=settings.codex_reasoning_effort,
            inspect_sandbox=settings.inspect_sandbox,
            fix_sandbox=settings.fix_sandbox,
            timeout_seconds=settings.timeout_seconds,
            max_result_chars=settings.max_result_chars,
        )

    return OpenCodeAdapter(
        opencode_bin=settings.opencode_bin,
        model=settings.opencode_model,
        timeout_seconds=settings.timeout_seconds,
        max_result_chars=settings.max_result_chars,
    )


def build_worker_service(settings: Settings) -> WorkerService:
    return WorkerService(
        executor=build_worker_executor(settings),
        allowed_roots=settings.allowed_roots,
    )
