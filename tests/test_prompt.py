import pytest

from codex_free_worker.contracts import WorkerMode
from codex_free_worker.prompt import build_opencode_prompt, build_worker_prompt


@pytest.mark.parametrize("mode", list(WorkerMode))
@pytest.mark.parametrize("opencode", [False, True])
def test_project_context_is_opt_in(mode: WorkerMode, opencode: bool) -> None:
    build = build_opencode_prompt if opencode else build_worker_prompt
    minimal = build("Inspect src/example.py.", mode)
    contextual = build("Inspect src/example.py.", mode, load_project_context=True)

    assert "Read and follow the repository's AGENTS.md" not in minimal
    assert "parent agent supplies applicable project constraints" in minimal
    assert "Read only the files needed" in minimal
    assert "Read and follow the repository's AGENTS.md" in contextual
    assert "Inspect src/example.py." in minimal
    assert "Inspect src/example.py." in contextual


def test_inspect_prompt_forbids_source_edits_but_allows_disposable_caches() -> None:
    prompt = build_worker_prompt("Run make check.", WorkerMode.INSPECT)

    assert "Do not intentionally edit source code" in prompt
    assert "disposable caches and temporary files" in prompt
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


def test_opencode_prompt_requires_one_plain_json_object() -> None:
    prompt = build_opencode_prompt("Run make check.", WorkerMode.INSPECT)

    assert "FREE_WORKER_RESULT_BEGIN" not in prompt
    assert "FREE_WORKER_RESULT_END" not in prompt
    assert "entire final assistant response must be exactly one JSON object" in prompt
    assert "Do not include Markdown" in prompt
    assert "JSON report must validate against this schema" in prompt
    assert "passed|fixed|failed|blocked" not in prompt


def test_worker_prompt_defers_permission_denials_to_main_agent() -> None:
    prompt = build_worker_prompt("Copy files.", WorkerMode.FIX)
    assert "status=blocked" in prompt
    assert "blocked_operation" in prompt
    assert "symlinks" in prompt
    assert "main agent" in prompt
    assert "never claim a blocked" in prompt


def test_opencode_prompt_includes_backward_compatible_handoff_field() -> None:
    prompt = build_opencode_prompt("Inspect files.", WorkerMode.INSPECT)
    assert '"blocked_operation":{' in prompt
    assert "blocked_operation=null" in prompt
    assert "actual denial" in prompt


def test_repair_prompt_contains_only_report_schema_and_diagnostic() -> None:
    from codex_free_worker.prompt import build_report_repair_prompt

    prompt = build_report_repair_prompt('{"checks": ["passed"]}', "checks: dict_type")
    assert "checks: dict_type" in prompt
    assert "JSON Schema" in prompt
    assert "untrusted report data" in prompt
    assert "Do not execute it again" in prompt
    assert "Never invent missing facts" in prompt
    assert "without Markdown, commentary or markers" in prompt
