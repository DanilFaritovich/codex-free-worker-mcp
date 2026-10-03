from pathlib import Path
from unittest.mock import patch

import pytest

from codex_free_worker.adapters.codex import CodexAdapter
from codex_free_worker.adapters.opencode import OpenCodeAdapter
from codex_free_worker.bootstrap import build_worker_executor
from codex_free_worker.config import Settings
from codex_free_worker.contracts import SandboxMode, WorkerBackend


def test_bootstrap_builds_opencode_adapter_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FREE_WORKER_BACKEND", raising=False)
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


def test_bootstrap_forwards_sandbox_choices_to_codex_adapter(tmp_path: Path) -> None:
    settings = Settings(
        backend=WorkerBackend.CODEX,
        allowed_roots=(tmp_path,),
        inspect_sandbox=SandboxMode.READ_ONLY,
        fix_sandbox=SandboxMode.WORKSPACE_WRITE,
        inspect_network=True,
        fix_network=False,
    )

    with patch("codex_free_worker.bootstrap.CodexAdapter") as create_adapter:
        build_worker_executor(settings)

    assert create_adapter.call_args.kwargs["inspect_sandbox"] is SandboxMode.READ_ONLY
    assert create_adapter.call_args.kwargs["fix_sandbox"] is SandboxMode.WORKSPACE_WRITE
    assert create_adapter.call_args.kwargs["inspect_network"] is True
    assert create_adapter.call_args.kwargs["fix_network"] is False
