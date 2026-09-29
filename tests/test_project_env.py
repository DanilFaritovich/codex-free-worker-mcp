from __future__ import annotations

import os
from pathlib import Path

import pytest

from codex_free_worker.project_env import build_project_env, resolve_backend_binary


def test_no_target_venv_keeps_inherited_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/parent/bin")
    monkeypatch.setenv("VIRTUAL_ENV", "/parent/venv")

    child_env = build_project_env(tmp_path)

    assert child_env["PATH"] == "/parent/bin"
    assert child_env["VIRTUAL_ENV"] == "/parent/venv"


def test_root_venv_is_preferred_and_backend_is_secondary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".venv"
    backend = tmp_path / "backend" / ".venv"
    for path in (root, backend):
        (path / "bin").mkdir(parents=True)

    monkeypatch.setenv("PATH", "/parent/bin")
    monkeypatch.setenv("VIRTUAL_ENV", "/parent/venv")

    child_env = build_project_env(tmp_path)

    assert child_env["PATH"].split(os.pathsep) == [
        str(root / "bin"),
        str(backend / "bin"),
        "/parent/bin",
    ]
    assert child_env["VIRTUAL_ENV"] == str(root)
    assert os.environ["PATH"] == "/parent/bin"
    assert os.environ["VIRTUAL_ENV"] == "/parent/venv"


def test_backend_only_venv_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = tmp_path / "backend" / ".venv"
    (backend / "bin").mkdir(parents=True)
    monkeypatch.setenv("PATH", "/parent/bin")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    child_env = build_project_env(tmp_path)

    assert child_env["PATH"].split(os.pathsep) == [str(backend / "bin"), "/parent/bin"]
    assert child_env["VIRTUAL_ENV"] == str(backend)
    assert "VIRTUAL_ENV" not in os.environ


def test_backend_executable_uses_original_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert resolve_backend_binary("codex") == str(binary)
    assert resolve_backend_binary("/absolute/path/to/codex") == "/absolute/path/to/codex"
