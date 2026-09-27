# Codex Free Worker

Local MCP bridge that lets Codex delegate bounded execution loops to OpenCode.

The worker keeps raw test/build/CI output out of the primary-model context. OpenCode
inspects command output itself, can perform bounded execution loops, and returns only a
compact structured result to Codex.

The OpenCode model is a runtime choice configured through `FREE_WORKER_MODEL`; this
repository does not prescribe a particular model.

## Intended split

Use the worker when delegation is likely to save meaningful primary-model context or
avoid repeated command/diagnosis cycles.

Good worker targets:

- failing test suites with large output;
- CI/GitHub Actions and other large log inspection;
- Docker/Compose/build failures;
- `run -> diagnose -> mechanical fix -> rerun` loops;
- large repository searches and routine exploration;
- bounded repetitive or mechanical refactors;
- validation workflows where several commands may need to be run before a compact
  conclusion can be returned.

Keep on the primary model:

- architecture and public contracts;
- security decisions;
- migration/persistence strategy;
- concurrency/transaction design;
- deployment design;
- ambiguous behavior;
- final acceptance/review.

Small deterministic commands with tiny output are usually cheaper to run directly from
Codex. Examples include `git status`, `git diff --stat`, or a short successful
`make check`.

**Delegate whole execution loops rather than individual commands.**

## Requirements

- Python 3.11+
- OpenCode available as `opencode`
- a provider/model configured for OpenCode
- Codex CLI with stdio MCP support

The worker invokes OpenCode non-interactively with `opencode run`, `--auto`, `--dir`,
`--model`, and `--format json`.

## Native install (recommended)

Native mode is simplest because OpenCode gets the same repository paths and host tooling
as Codex.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make check
```

If the environment was created with a tool that does not seed `pip`, install/seed `pip`
before `pip install -e '.[dev]'`.

Check OpenCode separately with the same model you intend to configure for the worker:

```bash
export FREE_WORKER_MODEL="provider/model"

opencode run \
  --auto \
  --dir "$PWD" \
  --model "$FREE_WORKER_MODEL" \
  --format json \
  "Reply with OK"
```

## Connect to Codex

Add the MCP server to `~/.codex/config.toml` using absolute paths:

```toml
[mcp_servers.free_worker]
command = "/home/YOU/Work/codex-free-worker-mcp/.venv/bin/codex-free-worker"
args = ["stdio"]
cwd = "/home/YOU/Work/codex-free-worker-mcp"
startup_timeout_sec = 10
tool_timeout_sec = 900

[mcp_servers.free_worker.env]
FREE_WORKER_MODEL = "provider/model"
FREE_WORKER_OPENCODE_BIN = "/absolute/path/to/opencode"
```

`FREE_WORKER_OPENCODE_BIN` is optional when `opencode` is already available in the MCP
process `PATH`. To find the host path:

```bash
which opencode
```

Restart Codex after changing its config, then verify the server is visible:

```bash
codex mcp list
```

## MCP tool

The server exposes one tool:

```text
delegate_task(
    task: string,
    cwd: absolute repository path,
    mode: "inspect" | "fix" = "inspect"
)
```

`inspect` asks the worker not to modify repository files.

`fix` permits bounded mechanical changes within the delegated task. Architecture,
security, persistence, deployment policy, concurrency, public contracts, and other
ambiguous design decisions should be returned to the primary model instead.

### Inspect example

```text
Run the repository validation workflow. Do not modify files.
If it fails, identify only the meaningful failing stage, concise root cause, useful
path:line locations, and whether a primary-model decision is required.
Do not return raw logs.
```

### Fix example

```text
Run the repository validation workflow.
Fix only bounded mechanical formatting/lint/type/test issues without changing intended
behavior. Rerun the smallest useful checks, then the project-level validation.
Stop if an architectural or behavioral decision is required.
```

## Result returned to Codex

Example:

```json
{
  "status": "failed",
  "summary": "Type checking failed in the repository layer.",
  "changed_files": [],
  "checks": {"mypy": "failed"},
  "relevant_locations": ["backend/app/repository.py:47"],
  "needs_main_model_decision": false,
  "decision_required": null
}
```

Raw stdout/stderr from OpenCode is captured inside the MCP process and is not returned
to Codex by default.

Possible statuses:

- `passed` — delegated work completed without changes;
- `fixed` — bounded changes were made and validation succeeded;
- `failed` — the worker or delegated validation failed;
- `blocked` — continuing requires a decision from the primary model.

## Integrating with project standards or skills

This repository is designed to be referenced by Codex project standards, `AGENTS.md`,
or a reusable skill. The integration rule should decide **when delegation is worth it**;
it should not hard-code a model choice.

A suitable rule is:

```text
Prefer free_worker.delegate_task when a bounded execution loop is expected to produce
large logs, repeated run/diagnose/fix/rerun cycles, broad repository exploration, or
mechanical work that would otherwise consume substantial primary-model context.

Run tiny deterministic commands with small output directly when delegation overhead
would be larger than the output itself.

Delegate the whole execution loop rather than one shell command at a time.

Keep architecture, security, transaction/concurrency decisions, migration strategy,
deployment design, ambiguous behavior, public contracts, and final acceptance on the
primary model.

Raw logs stay with the worker. Ask for additional diagnostics only when the compact
result is insufficient.
```

### Suggested integration workflow

When integrating this MCP into another repository or standards repository:

1. Confirm `free_worker` is configured globally in Codex and visible through
   `codex mcp list`.
2. Add a project/organization rule or reusable skill describing the delegation boundary
   above.
3. Do not copy a concrete OpenCode model into project instructions; model selection is
   runtime configuration through `FREE_WORKER_MODEL`.
4. Prefer project-owned validation entry points such as `make check`, `make verify`, or
   equivalent commands when they exist.
5. Let the worker inspect raw output and iterate internally; return only the compact
   `WorkerResult` to the primary model.
6. Escalate to the primary model when `needs_main_model_decision=true` or when the
   compact result is insufficient for a safe decision.

A useful first integration test is:

```text
Use free_worker in inspect mode.
Run the repository validation command.
Do not modify files and do not run the command yourself.
Return only the compact worker result.
```

## Docker

The image contains the MCP server and OpenCode:

```bash
docker build -t codex-free-worker .
```

For stdio MCP, Codex can start Docker directly:

```toml
[mcp_servers.free_worker]
command = "docker"
args = [
  "run", "--rm", "-i",
  "-e", "FREE_WORKER_MODEL",
  "-e", "OPENROUTER_API_KEY",
  "-v", "/home/YOU/Work:/home/YOU/Work",
  "codex-free-worker"
]
tool_timeout_sec = 900
```

The mount deliberately preserves the same absolute repository paths because Codex passes
an absolute `cwd` to `delegate_task`.

Docker mode contains only generic tooling plus OpenCode. Delegated project checks may
need project runtimes, Docker CLI/socket, `gh`, or other tools already available on the
host. For that reason **native stdio is the recommended mode for development**.

## Security boundary

The bridge starts OpenCode through a fixed argument list and never uses `shell=True`.

OpenCode is started with `--auto` so the delegated worker can execute allowed actions
without interactive approval. The worker prompt forbids privilege escalation,
destructive Git operations, merges, production deployment, secret retrieval, and
unrelated edits.

These restrictions are prompt-level policy, not an OS sandbox. `inspect` is likewise an
instruction to the worker rather than a filesystem-level read-only guarantee. Keep normal
Codex/OpenCode permission controls enabled and do not expose secrets or production
credentials to an untrusted model/provider.

## Development

```bash
make fix
make check
```

Tests cover configuration, inspect/fix prompt boundaries, compact-result extraction from
noisy JSONL, refusal to forward raw logs, and OpenCode command construction.
