from __future__ import annotations

from codex_free_worker.adapters.opencode import OpenCodeAdapter
from codex_free_worker.config import Settings
from codex_free_worker.service import WorkerService


def build_worker_service(settings: Settings) -> WorkerService:
    executor = OpenCodeAdapter(
        opencode_bin=settings.opencode_bin,
        model=settings.opencode_model,
        timeout_seconds=settings.timeout_seconds,
        max_result_chars=settings.max_result_chars,
    )
    return WorkerService(executor=executor, allowed_roots=settings.allowed_roots)
