from codex_free_worker.models import WorkerMode
from codex_free_worker.prompt import build_worker_prompt


def test_inspect_prompt_is_read_only() -> None:
    prompt = build_worker_prompt("Run make check.", WorkerMode.INSPECT)
    assert "Do not modify repository files" in prompt
    assert "Raw logs stay with you" in prompt
    assert "FREE_WORKER_RESULT_BEGIN" in prompt
    assert "FREE_WORKER_RESULT_END" in prompt


def test_fix_prompt_allows_only_bounded_edits() -> None:
    prompt = build_worker_prompt("Fix formatter failures.", WorkerMode.FIX)
    assert "mechanical and bounded" in prompt
    assert "do not commit or push" in prompt.lower()
