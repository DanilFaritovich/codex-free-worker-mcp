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
enabled = true
required = false
startup_timeout_sec = 10
tool_timeout_sec = 960
enabled_tools = ["inspect_task", "fix_task"]

[mcp_servers.free_worker.env]
FREE_WORKER_MODEL = "provider/model"
FREE_WORKER_OPENCODE_BIN = "/absolute/path/to/opencode"
FREE_WORKER_ALLOWED_ROOTS = "/home/YOU/Work"
FREE_WORKER_TIMEOUT_SECONDS = "840"
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

## MCP tools

The server exposes two tools with separate intent:

```text
inspect_task(
    task: string,
    cwd: absolute repository path
)

fix_task(
    task: string,
    cwd: absolute repository path
)
```

`inspect_task` is for high-output validation, diagnosis, CI/build inspection, and broad
routine exploration. It instructs the worker not to modify repository files.

`fix_task` permits only bounded mechanical changes where intended behavior is already
clear. Architecture, security, persistence, migration policy, concurrency, deployment
design, public contracts, ambiguous behavior, and final acceptance stay with the
primary Codex model.

Both tools require `cwd` to resolve inside one of the absolute directories listed in
`FREE_WORKER_ALLOWED_ROOTS`. Symlink resolution is applied before that boundary check.

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

OpenCode JSONL stdout is consumed incrementally. Tool/log events are discarded instead
of being accumulated in memory, and only a compact marked result from a non-synthetic
OpenCode `text` event is retained. stderr is discarded by the bridge and is never
returned to Codex.

Possible statuses:

- `passed` — delegated work completed without changes;
- `fixed` — bounded changes were made and validation succeeded;
- `failed` — the worker or delegated validation failed;
- `blocked` — continuing requires a decision from the primary model.

## Integrating with Codex

The MCP server publishes shared delegation guidance through MCP server instructions.
When the server is connected, Codex receives that guidance together with the two tool
descriptions. When the server is unavailable and `required = false`, Codex continues
without the worker.

The server instructions intentionally keep the policy generic:

```text
Use the worker for bounded high-output execution loops, repeated
run/diagnose/fix/rerun cycles, broad routine exploration, or work that would consume
substantial primary-model context.

Run tiny deterministic commands directly.

Delegate whole execution loops rather than individual commands.

Keep architecture, security, persistence/migration strategy, concurrency, deployment
design, public contracts, ambiguous behavior, and final acceptance on the primary
model.
```

Project skills do not need to know about OpenCode, a particular provider, or a concrete
model. Model selection remains a host/runtime concern through `FREE_WORKER_MODEL`.

For stronger automatic use across all local repositories, an optional short rule may be
placed in the user's global `~/.codex/AGENTS.md`:

```text
When free_worker MCP tools are available, prefer them for bounded high-output execution
loops or repeated mechanical run/diagnose/fix/rerun work. If unavailable, continue
directly without treating their absence as an error. Keep design decisions and final
review on the primary model.
```

Do not copy that rule into every project unless the project intentionally needs a
different delegation policy.

### Suggested integration workflow

1. Install the worker natively and confirm OpenCode works with the configured model.
2. Configure `free_worker` globally in Codex with `required = false`.
3. Set `FREE_WORKER_ALLOWED_ROOTS` to the narrowest practical development root.
4. Restart Codex and verify the server with `codex mcp list`.
5. Prefer project-owned validation entry points such as `make check`, `make verify`,
   or equivalent commands inside delegated tasks.
6. Let the worker inspect raw output and iterate internally; the primary model reviews
   the compact `WorkerResult` and any resulting diff.
7. Escalate when `needs_main_model_decision=true` or the compact result is insufficient
   for a safe decision.
8. Keep commit planning, staging, commits, push, PR delivery, and final acceptance on
   the primary Codex model.

A useful first integration test is:

```text
Use free_worker.inspect_task.
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
  "-e", "FREE_WORKER_ALLOWED_ROOTS",
  "-e", "FREE_WORKER_TIMEOUT_SECONDS",
  "-e", "OPENROUTER_API_KEY",
  "-v", "/home/YOU/Work:/home/YOU/Work",
  "codex-free-worker"
]
required = false
tool_timeout_sec = 960

[mcp_servers.free_worker.env]
FREE_WORKER_ALLOWED_ROOTS = "/home/YOU/Work"
FREE_WORKER_TIMEOUT_SECONDS = "840"
```

The mount deliberately preserves the same absolute repository paths because Codex passes
an absolute `cwd` to the worker tools. The same path must also be covered by
`FREE_WORKER_ALLOWED_ROOTS`.

Docker mode contains only generic tooling plus OpenCode. Delegated project checks may
need project runtimes, Docker CLI/socket, `gh`, or other tools already available on the
host. For that reason **native stdio is the recommended mode for development**.

## Security boundary

The bridge starts OpenCode through a fixed argument list and never uses `shell=True`.

OpenCode is started with `--auto` so the delegated worker can execute allowed actions
without interactive approval. Before execution, the bridge resolves `cwd` and rejects
repositories outside `FREE_WORKER_ALLOWED_ROOTS`. The worker prompt forbids privilege
escalation, Git index/ref/history changes, commits, pushes, branch/tag mutation,
production deployment, secret retrieval, and unrelated edits.

These restrictions are still not an OS sandbox. `inspect_task` is an instruction-level
read-only boundary, so keep normal Codex/OpenCode permission controls enabled and do not
expose secrets or production credentials to an untrusted model/provider. The primary
Codex agent should review the working-tree diff after any delegated fix.

## Development

```bash
make fix
make check
```

Tests cover allowed-root configuration, server/tool delegation boundaries, inspect/fix
prompt policy, spoof-resistant compact-result extraction, large streamed JSONL, refusal
to forward raw logs, and OpenCode command construction.
