import pytest

from codex_free_worker.config import Settings


def test_default_model_is_north_mini_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FREE_WORKER_MODEL", raising=False)
    assert Settings.from_env().model == "openrouter/cohere/north-mini-code:free"
