from __future__ import annotations

import sys
from pathlib import Path

from mcp.server import MCPServer

from codex_free_worker.config import Settings
from codex_free_worker.models import WorkerMode, WorkerResult, WorkerStatus
from codex_free_worker.opencode import run_opencode_task

SERVER_INSTRUCTIONS = """
Use this worker for bounded repository execution loops that would otherwise produce
large logs, repeated run/diagnose/fix/rerun cycles, broad routine exploration, or
substantial primary-model context usage. Prefer direct Codex execution for tiny
deterministic commands with small output. Keep architecture, security, persistence and
migration strategy, concurrency, deployment design, public contracts, ambiguous
behavior, and final acceptance on the primary model. Delegate whole execution loops,
not individual shell commands.
""".strip()

server = MCPServer("codex-free-worker", instructions=SERVER_INSTRUCTIONS)


def _run_task(task: str, cwd: str, mode: WorkerMode) -> WorkerResult:
    try:
        settings = Settings.from_env()
        return run_opencode_task(
            task=task,
            cwd=Path(cwd),
            mode=mode,
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


@server.tool()
def inspect_task(task: str, cwd: str) -> WorkerResult:
    """Inspect a bounded high-output repository task without modifying files.

    Use this for validation, log diagnosis, CI/build inspection, or broad routine
    exploration when keeping raw output out of the primary Codex context is valuable.
    Prefer direct Codex execution for tiny deterministic commands. Do not delegate
    architecture, security, persistence, migration, concurrency, deployment design,
    public contracts, ambiguous decisions, or final acceptance.
    """

    return _run_task(task, cwd, WorkerMode.INSPECT)


@server.tool()
def fix_task(task: str, cwd: str) -> WorkerResult:
    """Repair bounded mechanical repository failures and validate the result.

    Use this for formatter/lint/type/test/build failures and repetitive local fixes where
    the intended behavior is already clear. The worker may edit task-scoped files, but
    never owns Git delivery. Stop and return control to the primary model when a design,
    security, persistence, migration, concurrency, deployment, or public-contract
    decision is required.
    """

    return _run_task(task, cwd, WorkerMode.FIX)


def main() -> None:
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport != "stdio":
        raise SystemExit("This MVP supports stdio transport only.")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
