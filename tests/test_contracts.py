from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from codex_free_worker.contracts import (
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
    item_properties = cast(dict[str, object], item_schema["properties"])
    item_required = cast(list[str], item_schema["required"])
    assert item_schema["additionalProperties"] is False
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
        }
    )

    result = codex_result.to_worker_result()
    assert result.status is WorkerStatus.FIXED
    assert result.checks == {"make fix": "passed", "make check": "passed"}
    assert result.changed_files == ["src/example.py"]
