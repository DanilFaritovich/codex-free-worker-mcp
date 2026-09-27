from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from mcp.server import MCPServer

from codex_free_worker.config import Settings
from codex_free_worker.models import WorkerMode, WorkerResult
from codex_free_worker.opencode import run_opencode_task

server = MCPServer("codex-free-worker")


@server.tool()
def delegate_task(
    task: str,
    cwd: str,
    mode: Literal["inspect", "fix"] = "inspect",
) -> WorkerResult:
    """Delegate a bounded repository execution task to the free OpenCode worker.

    Prefer this for tests, lint/typecheck/build/CI/GitHub inspection loops and bounded
    mechanical fixes. Raw command logs remain inside the worker process. Keep architecture,
    security, migration strategy, concurrency, deployment design, ambiguous behavior and
    final acceptance on the primary model.
    """
    return run_opencode_task(
        task=task,
        cwd=Path(cwd),
        mode=WorkerMode(mode),
        settings=Settings.from_env(),
    )


def main() -> None:
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport != "stdio":
        raise SystemExit("This MVP supports stdio transport only.")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
