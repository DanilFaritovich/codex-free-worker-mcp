from pathlib import Path

import pytest

from codex_free_worker.config import Settings
from codex_free_worker.contracts import ReasoningEffort, SandboxMode, WorkerBackend


def test_default_backend_remains_opencode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREE_WORKER_BACKEND", raising=False)

    assert Settings.from_env().backend is WorkerBackend.OPENCODE


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


def test_codex_defaults_to_luna_low(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREE_WORKER_CODEX_MODEL", raising=False)
    monkeypatch.delenv("FREE_WORKER_CODEX_REASONING_EFFORT", raising=False)

    settings = Settings.from_env()

    assert settings.codex_model == "gpt-6-luna"
    assert settings.codex_reasoning_effort is ReasoningEffort.LOW


def test_codex_backend_can_be_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREE_WORKER_BACKEND", "codex")

    assert Settings.from_env().backend is WorkerBackend.CODEX


def test_codex_sandbox_defaults_to_workspace_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREE_WORKER_INSPECT_SANDBOX", raising=False)
    monkeypatch.delenv("FREE_WORKER_FIX_SANDBOX", raising=False)

    settings = Settings.from_env()

    assert settings.inspect_sandbox is SandboxMode.WORKSPACE_WRITE
    assert settings.fix_sandbox is SandboxMode.WORKSPACE_WRITE


@pytest.mark.parametrize(
    ("inspect", "fix", "expected_inspect", "expected_fix"),
    [
        ("read-only", "workspace-write", SandboxMode.READ_ONLY, SandboxMode.WORKSPACE_WRITE),
        ("workspace-write", "read-only", SandboxMode.WORKSPACE_WRITE, SandboxMode.READ_ONLY),
    ],
)
def test_codex_sandbox_overrides_are_independent(
    monkeypatch: pytest.MonkeyPatch,
    inspect: str,
    fix: str,
    expected_inspect: SandboxMode,
    expected_fix: SandboxMode,
) -> None:
    monkeypatch.setenv("FREE_WORKER_INSPECT_SANDBOX", inspect)
    monkeypatch.setenv("FREE_WORKER_FIX_SANDBOX", fix)

    settings = Settings.from_env()

    assert settings.inspect_sandbox is expected_inspect
    assert settings.fix_sandbox is expected_fix


@pytest.mark.parametrize("key", ["FREE_WORKER_INSPECT_SANDBOX", "FREE_WORKER_FIX_SANDBOX"])
def test_codex_sandbox_rejects_unsupported_values(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv(key, "danger-full-access")
    with pytest.raises(ValueError, match=key):
        Settings.from_env()


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


def test_logging_defaults_and_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LOG_LEVEL", "LOG_FORMAT", "SERVICE_NAME", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.service_name == "codex-free-worker"
    assert settings.environment == "development"

    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("SERVICE_NAME", "my-worker")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    settings = Settings.from_env()
    assert settings.log_level == "WARNING"
    assert settings.log_format == "text"
    assert settings.service_name == "my-worker"
    assert settings.environment == "staging"


def test_invalid_logging_format_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "xml")
    with pytest.raises(ValueError, match="LOG_FORMAT"):
        Settings.from_env()
