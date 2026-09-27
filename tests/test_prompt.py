from codex_free_worker.contracts import WorkerMode
from codex_free_worker.prompt import build_opencode_prompt, build_worker_prompt


def test_inspect_prompt_is_read_only() -> None:
    prompt = build_worker_prompt("Run make check.", WorkerMode.INSPECT)

    assert "Do not modify repository files" in prompt
    assert "Raw logs stay with you" in prompt
    assert "FREE_WORKER_RESULT_BEGIN" not in prompt


def test_fix_prompt_allows_only_bounded_edits() -> None:
    prompt = build_worker_prompt("Fix formatter failures.", WorkerMode.FIX)

    assert "mechanical and bounded" in prompt
    assert "never stage files, commit, push" in prompt.lower()


def test_worker_never_owns_git_delivery() -> None:
    prompt = build_worker_prompt("Commit and push the fix.", WorkerMode.FIX)
    lowered = prompt.lower()

    assert "never stage files, commit, push" in lowered
    assert "modify Git index, refs, or history".lower() in lowered


def test_opencode_prompt_adds_transport_markers() -> None:
    prompt = build_opencode_prompt("Run make check.", WorkerMode.INSPECT)

    assert "FREE_WORKER_RESULT_BEGIN" in prompt
    assert "FREE_WORKER_RESULT_END" in prompt
