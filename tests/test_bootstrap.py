from pathlib import Path

from codex_free_worker.adapters.codex import CodexAdapter
from codex_free_worker.adapters.opencode import OpenCodeAdapter
from codex_free_worker.bootstrap import build_worker_executor
from codex_free_worker.config import Settings
from codex_free_worker.contracts import WorkerBackend


def test_bootstrap_builds_opencode_adapter_by_default(tmp_path: Path) -> None:
    settings = Settings(
        allowed_roots=(tmp_path,),
        opencode_model="provider/model",
    )

    assert isinstance(build_worker_executor(settings), OpenCodeAdapter)


def test_bootstrap_builds_codex_adapter_when_selected(tmp_path: Path) -> None:
    settings = Settings(
        backend=WorkerBackend.CODEX,
        allowed_roots=(tmp_path,),
    )

    assert isinstance(build_worker_executor(settings), CodexAdapter)
