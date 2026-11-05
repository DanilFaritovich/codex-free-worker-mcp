from pathlib import Path
from unittest.mock import patch

import pytest

from codex_free_worker import server as server_module
from codex_free_worker.contracts import WorkerMode, WorkerResult, WorkerStatus
from codex_free_worker.server import SERVER_INSTRUCTIONS, server


def test_server_instructions_define_delegation_boundary() -> None:
    assert "bounded repository execution loops" in SERVER_INSTRUCTIONS
    assert "final acceptance on the primary model" in SERVER_INSTRUCTIONS


def test_server_exposes_separate_inspect_and_fix_tools() -> None:
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}

    assert tool_names == {"inspect_task", "fix_task"}


@pytest.mark.parametrize("mode", list(WorkerMode))
@pytest.mark.parametrize("load_context", [None, False, True])
def test_tool_forwards_context_flag_to_executor(
    tmp_path: Path, mode: WorkerMode, load_context: bool | None
) -> None:
    tool = server_module.inspect_task if mode is WorkerMode.INSPECT else server_module.fix_task
    expected = WorkerResult(status=WorkerStatus.PASSED, summary="ok")
    with (
        patch("codex_free_worker.server.Settings.from_env"),
        patch.object(server_module, "build_worker_service") as build_service,
    ):
        service = build_service.return_value
        service.execute.return_value = expected
        result = (
            tool("Inspect.", str(tmp_path))
            if load_context is None
            else tool("Inspect.", str(tmp_path), load_project_context=load_context)
        )

    request = service.execute.call_args.args[0]
    assert request.load_project_context is (load_context is True)
    assert request.mode is mode
    assert result is expected


def test_mcp_schema_exposes_optional_context_flag() -> None:
    for tool in server._tool_manager.list_tools():
        flag = tool.parameters["properties"]["load_project_context"]
        assert flag["type"] == "boolean"
        assert flag["default"] is False
        assert "load_project_context" not in tool.parameters.get("required", [])
