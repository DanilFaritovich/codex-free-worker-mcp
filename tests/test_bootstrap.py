from pathlib import Path

from codex_free_worker.adapters.codex import CodexAdapter
from codex_free_worker.adapters.opencode import OpenCodeAdapter
from codex_free_worker.bootstrap import build_worker_executor
from codex_free_worker.config import Settings


def test_bootstrap_builds_opencode_adapter_by_default(tmp_path: Path) -> None:
    settings = Settings(
        FREE_WORKER_ALLOWED_ROOTS=str(tmp_path),
        FREE_WORKER_OPENCODE_MODEL="provider/model",
    )

    assert isinstance(build_worker_executor(settings), OpenCodeAdapter)


def test_bootstrap_builds_codex_adapter_when_selected(tmp_path: Path) -> None:
    settings = Settings(
        FREE_WORKER_BACKEND="codex",
        FREE_WORKER_ALLOWED_ROOTS=str(tmp_path),
    )

    assert isinstance(build_worker_executor(settings), CodexAdapter)
