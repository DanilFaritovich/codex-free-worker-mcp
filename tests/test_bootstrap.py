from pathlib import Path

from codex_free_worker.adapters.opencode import OpenCodeAdapter
from codex_free_worker.bootstrap import build_worker_service
from codex_free_worker.config import Settings


def test_bootstrap_builds_opencode_service(tmp_path: Path) -> None:
    settings = Settings(
        FREE_WORKER_ALLOWED_ROOTS=str(tmp_path),
        FREE_WORKER_OPENCODE_MODEL="provider/model",
    )

    service = build_worker_service(settings)

    assert isinstance(service._executor, OpenCodeAdapter)
