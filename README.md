[English](README.md) | [Русский](README.ru.md)

# Codex Free Worker

Local MCP bridge that lets Codex delegate bounded execution loops to a configurable
execution backend: OpenCode or an isolated child Codex CLI.

The worker keeps raw test/build/CI output out of the primary-model context. The selected
backend inspects command output itself, can perform bounded execution loops, and returns
only a compact structured result to the primary Codex agent.

Backend and model selection are runtime choices. Existing installations keep OpenCode as
the default backend; set `FREE_WORKER_BACKEND=codex` to use Codex instead. There is no
automatic fallback between backends.

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

- Python 3.14+
- Codex CLI with stdio MCP support
- for the OpenCode backend: OpenCode plus a configured provider/model
- for the Codex backend: a working Codex CLI authentication/session

The OpenCode backend invokes `opencode run` non-interactively. The Codex backend invokes
`codex exec` with an explicit model, reasoning effort, sandbox, structured output schema,
`--ephemeral`, and `--ignore-user-config`. The latter prevents the child worker from
loading the parent user's Codex MCP configuration, which avoids recursive delegation.

## Quick start: native install (recommended)

Native mode is simplest because OpenCode gets the same repository paths and host tooling
as Codex.

```bash
git clone https://github.com/DanilFaritovich/codex-free-worker-mcp.git
cd codex-free-worker-mcp

python3.14 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make check
```

If the environment was created with a tool that does not seed `pip`, install/seed `pip`
before `pip install -e '.[dev]'`.

For the OpenCode backend, check OpenCode separately with the same model you intend to
configure for the worker:

```bash
export FREE_WORKER_MODEL="provider/model"

opencode run \
  --auto \
  --dir "$PWD" \
  --model "$FREE_WORKER_MODEL" \
  --format json \
  "Reply with OK"
```

## Backend configuration

Select one backend explicitly when you want to move away from the backward-compatible
OpenCode default:

```text
FREE_WORKER_BACKEND=opencode
# or
FREE_WORKER_BACKEND=codex
```

The Codex backend defaults to `gpt-6-luna` with `low` reasoning effort. Both are
configurable. **Both `inspect_task` and `fix_task` default to `workspace-write`**
so validators can write disposable caches and temporary files. Each sandbox can be
changed independently to `read-only` through `FREE_WORKER_INSPECT_SANDBOX` and
`FREE_WORKER_FIX_SANDBOX`. Only `workspace-write` and `read-only` are supported.
The child session is ephemeral and ignores the user's Codex config, but keeps normal
Codex authentication. These settings apply to the Codex backend, not OpenCode.

**Important:** `workspace-write` gives the child permission to modify repository
files. The `inspect_task` prompt still forbids intentional edits to source code,
tests, docs, configuration and tracked files, but a model instruction is **not** a
filesystem security boundary. Review the worktree after delegated inspections, and keep
MCP tool approval on `prompt` when this permission matters. In `read-only`, validators
that write caches (for example Ruff or pytest) may fail unless configured accordingly.

There is intentionally no automatic backend fallback in this version.

### Automatic project virtual environment

When launching a child Codex or OpenCode process, the MCP bridge checks the target
repository `cwd` for `.venv/bin` and `backend/.venv/bin`. Existing directories
are prepended to the **child process's** `PATH` (root `.venv` first) and the first
available environment is set as `VIRTUAL_ENV`. This lets `make check` find project
tools such as Ruff, mypy, and pytest without an extra `PATH=...` prefix.
The MCP server's own environment is not modified; the configured Codex/OpenCode binary
is resolved against the *original* PATH, before project-local paths are prepended.

This discovers **existing** virtual environments; it does not install dependencies,
activate shell scripts, or fix failing project tests. If no matching environment is
present, the child inherits the original environment. In monorepos with custom virtual
environment layouts, configure PATH in your project Makefile or task explicitly.

## Provider authentication

The worker does not manage provider credentials itself. For OpenCode, the configured
provider must already be usable. For the Codex backend, the local Codex CLI must already
be authenticated.

If OpenCode is already authenticated through its own provider configuration, no extra
credential needs to be stored in the MCP block.

If a provider expects an environment variable, export it in the shell that starts Codex
and whitelist it for the stdio MCP process. For example, with OpenRouter:

```bash
export OPENROUTER_API_KEY="..."
```

```toml
[mcp_servers.free_worker]
env_vars = ["OPENROUTER_API_KEY"]
```

Do not hard-code provider secrets in repository files or example configuration.

A repository-local `.env` file is **not automatically loaded by this native MCP
server**. `.env.example` documents supported variables; use your shell, secret manager,
OpenCode provider configuration, or Codex MCP environment forwarding to provide actual
credentials.

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
default_tools_approval_mode = "prompt"

[mcp_servers.free_worker.env]
FREE_WORKER_BACKEND = "codex"

# Codex backend
FREE_WORKER_CODEX_BIN = "/absolute/path/to/codex"
FREE_WORKER_CODEX_MODEL = "gpt-6-luna"
FREE_WORKER_CODEX_REASONING_EFFORT = "low"
FREE_WORKER_INSPECT_SANDBOX = "workspace-write"
FREE_WORKER_FIX_SANDBOX = "workspace-write"

# Shared
FREE_WORKER_ALLOWED_ROOTS = "/home/YOU/Work"
FREE_WORKER_TIMEOUT_SECONDS = "840"
FREE_WORKER_MAX_RESULT_CHARS = "8000"

# For OpenCode instead:
# FREE_WORKER_BACKEND = "opencode"
# FREE_WORKER_OPENCODE_BIN = "/absolute/path/to/opencode"
# FREE_WORKER_OPENCODE_MODEL = "provider/model"
```

The backend executable path is optional when the corresponding executable is already in
the MCP process `PATH`:

```bash
which codex
which opencode
```

Restart Codex after changing its config, then verify the server is visible:

```bash
codex mcp list
```

The values inside `[mcp_servers.free_worker.env]` in `~/.codex/config.toml` are passed
to this MCP server as environment variables. The worker **does not read the parent
`config.toml` directly**. To switch to a no-write inspection sandbox, set:

```toml
[mcp_servers.free_worker.env]
FREE_WORKER_INSPECT_SANDBOX = "read-only"
FREE_WORKER_FIX_SANDBOX = "workspace-write"
```

These are alternative values for the existing MCP environment block: edit the existing
keys rather than adding a second table. Restart the parent Codex CLI to apply changes.

Because inspection now defaults to `workspace-write`, keep both tools on `prompt` for
approval unless you deliberately accept the additional filesystem-write risk.

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
routine exploration. It forbids intentional source/configuration edits but permits disposable
cache and temporary-file writes where the configured sandbox allows them.

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

OpenCode JSONL stdout is consumed incrementally and only a compact marked result from a
non-synthetic OpenCode `text` event is retained. The Codex backend instead supplies the
strict Pydantic JSON Schema through `codex exec --output-schema`, with checks represented
as fixed-shape list items. It converts the result back to the public `WorkerResult`
dictionary-shaped checks and validates it locally. Raw stderr is discarded by both adapters and is never
returned to the primary Codex agent.

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

Project skills do not need to know which execution backend, provider, or model is
selected. Backend/model selection remains a host/runtime concern through the MCP
environment configuration.

### Using codex-development-standards

This MCP is host-level infrastructure. Application repositories should not depend on
this repository directly.

If you use
[`codex-development-standards`](https://github.com/DanilFaritovich/codex-development-standards),
its task-development workflow can describe **when** an available optional execution
worker should be used. Standards are synchronized into each project independently; the
MCP stays configured once in the user's Codex configuration.

The intended layering is:

```text
~/.codex/config.toml
        |
        +--> free_worker MCP (inspect_task / fix_task)

codex-development-standards
        |
        +--> task-development-workflow
                |
                +--> optional delegation policy

project repository
        |
        +--> synchronized project-local standards
```

This keeps projects portable:

- when the MCP is available, Codex may delegate suitable bounded execution loops;
- when it is unavailable and `required = false`, Codex continues directly;
- project instructions do not need to know the OpenCode provider or model;
- Git delivery and final acceptance remain with the primary Codex model.

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

1. Install the worker natively and confirm the selected backend works independently.
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

## Troubleshooting

### Codex does not show the server

```bash
codex mcp list
```

Confirm that the configured `command` and `cwd` are absolute paths and restart Codex
after changing `~/.codex/config.toml`.

### Backend executable is not found

```bash
which codex
which opencode
```

Set `FREE_WORKER_CODEX_BIN` or `FREE_WORKER_OPENCODE_BIN` to the corresponding absolute
path, or make sure the executable is in the environment inherited by the MCP process.

### `cwd is outside FREE_WORKER_ALLOWED_ROOTS`

Add the narrowest parent directory that should contain delegated repositories. The
worker resolves symlinks before enforcing this boundary.

### Worker returns `failed`

First run the selected backend directly. Verify model availability and authentication
outside the MCP before debugging the bridge.

The bridge intentionally does not return raw stderr or large logs to the primary Codex
agent. Use the backend CLI directly for provider/runtime diagnosis when needed.

## Docker

The image contains the MCP server, OpenCode, and the Codex CLI:

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

Docker mode contains the worker CLIs but delegated project checks may still need project
runtimes, Docker CLI/socket, `gh`, authentication state, or other tools already available
on the host. For that reason **native stdio is the recommended mode for development**.

## Security boundary

Both adapters start their backend through fixed argument lists and never use
`shell=True`. Before execution, the shared service resolves `cwd` and rejects
repositories outside `FREE_WORKER_ALLOWED_ROOTS`.

OpenCode still relies on an instruction-level read-only boundary in `inspect_task`.
Codex additionally enforces `read-only` for inspect and `workspace-write` for fix through
its sandbox. The Codex child also uses `--ignore-user-config`, preventing it from loading
the parent user's MCP configuration.

The shared worker prompt forbids privilege escalation, Git index/ref/history changes,
commits, pushes, branch/tag mutation, production deployment, secret retrieval, and
unrelated edits. These controls are not a complete OS security boundary; keep normal
backend permission controls enabled and do not expose secrets or production credentials
to an untrusted provider. The primary Codex agent should review the working-tree diff
after any delegated fix.

## Structured logging (Loki / Grafana ready)

The MCP transport uses **stdout exclusively for protocol messages**. The service writes
one JSON object per line to **stderr** (also in Docker), so application logging cannot
corrupt the stdio protocol. No extra logging dependency or in-container log files are
required. Local human-readable logs are optional.

Configure these environment variables in the environment **inherited by the MCP server**
(or add them to the existing `[mcp_servers.free_worker.env]` block in
`~/.codex/config.toml`):

```bash
LOG_LEVEL=INFO
LOG_FORMAT=json
SERVICE_NAME=codex-free-worker
ENVIRONMENT=production
```

`LOG_LEVEL` accepts `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
`LOG_FORMAT` accepts `json` (default) or `text`. By default `ENVIRONMENT` is
`development`; `compose.yml` defaults to `production`. The Docker Compose service
forwards these four variables to the MCP process.

Example of an emitted application event (illustrative values):

```json
{"timestamp":"2026-09-29T12:00:00.000Z","level":"INFO","logger":"codex_free_worker.server","message":"Worker task completed.","service":"codex-free-worker","environment":"production","request_id":"f0e2c1","event":"worker_completed","backend":"codex","mode":"fix","status":"fixed","duration_ms":1380,"changed_files_count":1,"check_count":2}
```

Stable `event` values include `server_starting`, `worker_started`,
`worker_completed`, `worker_failed`, `backend_timeout`,
`backend_process_failed` and `backend_executable_missing`. A generated
`request_id` correlates records for one worker tool call. Duration is in milliseconds.
Failures report safe structured metadata such as `error_type`, `exit_code`, and
`timeout_seconds`. Unexpected exception stack frames contain only filenames, line
numbers and function names.

**Never** log task/prompt text, model stdout/stderr, provider credentials, complete
repository paths, raw exception messages or private result payloads. The subprocess
stderr streams remain discarded; only safe error metadata is logged. `request_id`
is placed in the JSON body, **not** promoted to a Loki label.

For a later Grafana integration, collect the container/runtime stderr stream using a
Loki-compatible collector (for example, Grafana Alloy), forward JSON Lines to Loki, and
query them in Grafana. Configure low-cardinality labels such as `service` and
`environment` in the collector; keep request IDs and other high-cardinality values in
the JSON document. Example LogQL **after the collector defines the `service` label**:

```logql
{service="codex-free-worker"} | json | event="worker_failed"
```

This repository does **not** deploy Loki, Grafana, a collector or a dashboard. It also
does not yet capture usage/token metrics from child Codex sessions.

## Development

```bash
make fix
make check
```

Tests cover Pydantic contracts, allowed-root enforcement, backend selection, server/tool
delegation boundaries, inspect/fix policy, OpenCode JSONL spoof resistance, Codex command
isolation/sandbox selection, structured-result validation, timeouts, missing executables,
and refusal to forward raw logs. CI runs the project checks on Python 3.14 plus a Docker build.
