from __future__ import annotations

from codex_free_worker.contracts import WorkerMode

_RESULT_START = "FREE_WORKER_RESULT_BEGIN"
_RESULT_END = "FREE_WORKER_RESULT_END"


def build_worker_prompt(task: str, mode: WorkerMode) -> str:
    permission_text = (
        (
            "You are in INSPECT mode. Do not intentionally edit source code, tests, "
            "documentation, configuration, or tracked files. Validation commands may "
            "create disposable caches and temporary files when the sandbox allows it."
        )
        if mode is WorkerMode.INSPECT
        else (
            "You are in FIX mode. You may edit repository files only when the requested "
            "change is mechanical and bounded by the task."
        )
    )

    return f"""
You are an execution worker controlled by a senior coding agent.

Work inside the repository provided by the execution backend.
Read and follow the repository's AGENTS.md and applicable project-local instructions
before acting. Prefer the repository's public Makefile commands when they exist.

{permission_text}

Your role:
- execute bounded repository tasks;
- run tests, lint, type checks, builds, Docker/Compose checks and GitHub/gh inspection;
- inspect command stdout/stderr yourself;
- in FIX mode, repair only mechanical/local issues within the task and rerun the smallest
  useful validation;
- stop when an architectural, security, persistence, migration-policy, deployment-policy,
  concurrency, public-API, or other ambiguous design decision is required.

Safety:
- never use sudo, su, permission-bypass chmod/chown, destructive git reset, force push,
  merge, production deployment, or secret retrieval;
- never stage files, commit, push, merge, rebase, create/delete/switch branches or tags,
  or otherwise modify Git index, refs, or history;
- do not modify unrelated files;
- do not paste raw command logs into the final response;
- do not include private reasoning traces.

Permission handoff:
- If a necessary file read/write, command, or network operation is denied by the sandbox,
  filesystem permissions, or an approval boundary, stop that operation. Do not bypass it
  with sudo, chmod/chown, symlinks, alternate privileged tools, or an unrestricted sandbox.
- Return status=blocked, needs_main_model_decision=true, and a concise decision_required
  describing the smallest intended action and why it is necessary.
- Include blocked_operation with kind (file-read, file-write, command, network, or other),
  target (path or non-secret destination), and reason (the actual denial). This is
  descriptive information, not a command for the parent to execute blindly.
- Do not include credentials, private data, raw logs, or shell snippets carrying secrets
  in the handoff. Report any completed changes/checks accurately; never claim a blocked
  task succeeded.
- For a non-permission architectural or ambiguous decision, report blocked with
  blocked_operation=null and explain the decision_required instead.
- Never ask the child process to grant itself permissions. The main agent decides whether
  to request user approval using its own available mechanisms and may perform a narrowly
  scoped approved action. If no such mechanism is available, it must stop.

Raw logs stay with you. Return only a compact final report.

TASK:
{task.strip()}
""".strip()


def build_opencode_prompt(task: str, mode: WorkerMode) -> str:
    prompt = build_worker_prompt(task, mode)
    return f"""
{prompt}

At the very end of your response, output exactly one JSON object between these markers:

{_RESULT_START}
{{
  "status": "passed|fixed|failed|blocked",
  "summary": "concise result/root cause",
  "changed_files": ["path"],
  "checks": {{"command or stage": "passed|failed|skipped"}},
  "relevant_locations": ["path:line"],
  "needs_main_model_decision": false,
  "decision_required": null,
  "blocked_operation": null
}}
{_RESULT_END}

Rules for the JSON report:
- Keep it compact.
- Never place raw stdout/stderr in it.
- For a failure, include only the meaningful failing stage/root cause and useful locations.
- If a main-model decision is required, use status=blocked,
  needs_main_model_decision=true, and describe only the exact decision needed.
- For a denied operation, also populate blocked_operation with kind, target and reason;
  otherwise use null. Never return an executable approval or privileged command.
- If you repaired a mechanical issue successfully, use status=fixed.
""".strip()


def result_markers() -> tuple[str, str]:
    return _RESULT_START, _RESULT_END
