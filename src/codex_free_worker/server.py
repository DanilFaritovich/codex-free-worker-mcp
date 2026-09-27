from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from mcp.server import MCPServer

from codex_free_worker.config import Settings
from codex_free_worker.models import WorkerMode, WorkerResult, WorkerStatus
from codex_free_worker.opencode import run_opencode_task

server = MCPServer("codex-free-worker")


@server.tool()
def delegate_task(
    task: str,
    cwd: str,
    mode: Literal["inspect", "fix"] = "inspect",
) -> WorkerResult:
    """Delegate a bounded repository task to OpenCode."""

    try:
        settings = Settings.from_env()

        return run_opencode_task(
            task=task,
            cwd=Path(cwd),
            mode=WorkerMode(mode),
            settings=settings,
        )
    except Exception as exc:
        return WorkerResult(
            status=WorkerStatus.FAILED,
            summary=f"{type(exc).__name__}: {exc}",
            changed_files=[],
            checks={"worker": "failed"},
            relevant_locations=[],
            needs_main_model_decision=False,
            decision_required=None,
        )


def main() -> None:
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport != "stdio":
        raise SystemExit("This MVP supports stdio transport only.")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
