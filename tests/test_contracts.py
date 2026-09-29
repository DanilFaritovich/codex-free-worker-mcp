from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from codex_free_worker.contracts import (
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
