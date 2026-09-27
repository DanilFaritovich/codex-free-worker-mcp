from pathlib import Path

import pytest

from codex_free_worker.config import Settings


def test_default_opencode_model_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREE_WORKER_OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("FREE_WORKER_MODEL", raising=False)

    assert Settings.from_env().opencode_model == "openrouter/cohere/north-mini-code:free"


def test_legacy_model_environment_variable_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FREE_WORKER_OPENCODE_MODEL", raising=False)
    monkeypatch.setenv("FREE_WORKER_MODEL", "provider/legacy-model")

    assert Settings.from_env().opencode_model == "provider/legacy-model"


def test_allowed_roots_are_parsed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv(
        "FREE_WORKER_ALLOWED_ROOTS",
        f"{first}{__import__('os').pathsep}{second}",
    )

    assert Settings.from_env().allowed_roots == (first.resolve(), second.resolve())


def test_relative_allowed_root_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREE_WORKER_ALLOWED_ROOTS", "relative/path")

    with pytest.raises(ValueError, match="absolute paths"):
        Settings.from_env()
