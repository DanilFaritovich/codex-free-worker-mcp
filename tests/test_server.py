from codex_free_worker.server import SERVER_INSTRUCTIONS, server


def test_server_instructions_define_delegation_boundary() -> None:
    assert "bounded repository execution loops" in SERVER_INSTRUCTIONS
    assert "final acceptance on the primary model" in SERVER_INSTRUCTIONS


def test_server_exposes_separate_inspect_and_fix_tools() -> None:
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}

    assert tool_names == {"inspect_task", "fix_task"}
