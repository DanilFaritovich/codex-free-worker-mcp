from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from codex_free_worker.contracts import (
    BlockedOperation,
    BlockedOperationKind,
    CodexWorkerResult,
    WorkerMode,
    WorkerRequest,
    WorkerResult,
    WorkerStatus,
    worker_result_json_schema,
)


def test_worker_request_strips_task() -> None:
    request = WorkerRequest(
        task="  Run make check.  ",
        cwd=Path("/tmp/repo"),
        mode=WorkerMode.INSPECT,
    )

    assert request.task == "Run make check."


def test_worker_request_rejects_empty_task() -> None:
    with pytest.raises(ValidationError, match="task"):
        WorkerRequest(task="   ", cwd=Path("/tmp/repo"), mode=WorkerMode.INSPECT)


def test_worker_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        WorkerResult.model_validate(
            {
                "status": WorkerStatus.PASSED,
                "summary": "Checks passed.",
                "unexpected": True,
            }
        )


def test_worker_result_schema_requires_complete_contract() -> None:
    schema = worker_result_json_schema()
    properties = cast(dict[str, object], schema["properties"])
    required = cast(list[str], schema["required"])

    assert schema["additionalProperties"] is False
    assert set(required) == set(properties)


def test_codex_schema_uses_closed_object_for_each_check() -> None:
    schema = worker_result_json_schema()
    properties = cast(dict[str, object], schema["properties"])
    checks_schema = cast(dict[str, object], properties["checks"])
    assert checks_schema["type"] == "array"

    item_schema = cast(dict[str, object], checks_schema["items"])
    assert item_schema["$ref"] == "#/$defs/CodexCheck"
    definitions = cast(dict[str, object], schema["$defs"])
    item_definition = cast(dict[str, object], definitions["CodexCheck"])
    item_properties = cast(dict[str, object], item_definition["properties"])
    item_required = cast(list[str], item_definition["required"])
    assert item_definition["additionalProperties"] is False
    assert set(item_properties) == {"name", "result"}
    assert set(item_required) == set(item_properties)


def test_codex_result_converts_to_public_worker_contract() -> None:
    codex_result = CodexWorkerResult.model_validate(
        {
            "status": "fixed",
            "summary": "Normalized formatting.",
            "changed_files": ["src/example.py"],
            "checks": [
                {"name": "make fix", "result": "passed"},
                {"name": "make check", "result": "passed"},
            ],
            "relevant_locations": [],
            "needs_main_model_decision": False,
            "decision_required": None,
            "blocked_operation": None,
        }
    )

    result = codex_result.to_worker_result()
    assert result.status is WorkerStatus.FIXED
    assert result.checks == {"make fix": "passed", "make check": "passed"}
    assert result.changed_files == ["src/example.py"]


def test_permission_handoff_schema_is_closed_and_required_in_codex_envelope() -> None:
    schema = worker_result_json_schema()
    properties = cast(dict[str, object], schema["properties"])
    assert "blocked_operation" in properties
    assert "blocked_operation" in cast(list[str], schema["required"])

    definitions = cast(dict[str, object], schema["$defs"])
    blocked_schema = cast(dict[str, object], definitions["BlockedOperation"])
    assert blocked_schema["additionalProperties"] is False
    assert set(cast(list[str], blocked_schema["required"])) == {
        "kind", "target", "reason"
    }


def test_worker_result_accepts_permission_handoff() -> None:
    result = WorkerResult(
        status=WorkerStatus.BLOCKED,
        summary="Protected path was not writable.",
        needs_main_model_decision=True,
        decision_required="Ask whether to copy the selected files.",
        blocked_operation=BlockedOperation(
            kind=BlockedOperationKind.FILE_WRITE,
            target=".agents/skills",
            reason="Read-only file system",
        ),
    )
    assert result.blocked_operation is not None
    assert result.blocked_operation.kind is BlockedOperationKind.FILE_WRITE


@pytest.mark.parametrize(
    ("status", "needs_decision", "decision"),
    [
        (WorkerStatus.PASSED, True, "Ask."),
        (WorkerStatus.BLOCKED, False, "Ask."),
        (WorkerStatus.BLOCKED, True, None),
    ],
)
def test_worker_result_rejects_inconsistent_permission_handoff(
    status: WorkerStatus,
    needs_decision: bool,
    decision: str | None,
) -> None:
    with pytest.raises(ValidationError, match="blocked_operation"):
        WorkerResult(
            status=status,
            summary="Cannot write.",
            needs_main_model_decision=needs_decision,
            decision_required=decision,
            blocked_operation=BlockedOperation(
                kind=BlockedOperationKind.FILE_WRITE,
                target=".agents/skills",
                reason="Denied",
            ),
        )


def test_codex_schema_does_not_execute_blocked_operation() -> None:
    codex_result = CodexWorkerResult.model_validate(
        {
            "status": "blocked",
            "summary": "Denied.",
            "changed_files": [],
            "checks": [],
            "relevant_locations": [],
            "needs_main_model_decision": True,
            "decision_required": "Decide whether the write is necessary.",
            "blocked_operation": {
                "kind": "file-write",
                "target": ".agents/skills",
                "reason": "Denied",
            },
        }
    )
    result = codex_result.to_worker_result()
    assert result.blocked_operation is not None
    assert result.blocked_operation.target == ".agents/skills"
