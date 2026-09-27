# Codex Free Worker

Local MCP bridge that lets Codex/GPT-5.6 Sol delegate low-risk execution loops to
OpenCode using one fixed free model:

`openrouter/cohere/north-mini-code:free`

The worker keeps raw test/build/CI logs out of the primary-model context. OpenCode
inspects them itself and returns only a compact structured result.

## Intended split

Delegate to the worker:

- `make fix`, `make check`, `make verify`, tests, lint, mypy, builds;
- Docker/Compose validation;
- CI/GitHub/`gh` inspection and large log inspection;
- routine repository exploration;
- bounded mechanical fixes.

Keep on the primary model:

- architecture and public contracts;
- security decisions;
- migration/persistence strategy;
- concurrency/transaction design;
- deployment design;
- ambiguous behavior;
- final acceptance/review.

## Requirements

- Python 3.11+
- OpenCode available as `opencode`
- OpenRouter configured for OpenCode (`OPENROUTER_API_KEY` is enough for a clean setup)
- Codex CLI with stdio MCP support

OpenCode currently supports `opencode run` with `--standalone`, `--dir`, `--model`,
and `--format json`; this server uses that non-interactive mode.

## Native install (recommended)

Native mode is simplest because OpenCode gets the same repository path and host tooling as
Codex.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make check
```

Check OpenCode separately:

```bash
opencode run --standalone \
  --dir "$PWD" \
  --model openrouter/cohere/north-mini-code:free \
  "Reply with OK"
```

## Connect to Codex

Add this to `~/.codex/config.toml` using absolute paths:

```toml
[mcp_servers.free_worker]
command = "/home/YOU/Work/codex-free-worker/.venv/bin/codex-free-worker"
args = ["stdio"]
cwd = "/home/YOU/Work/codex-free-worker"
tool_timeout_sec = 900
```

Restart Codex after changing its config.

The MCP server exposes one tool:

```text
delegate_task(
    task: string,
    cwd: absolute repository path,
    mode: "inspect" | "fix" = "inspect"
)
```

### Inspect example

```text
Run `make verify`. Do not modify files. If it fails, identify only the first meaningful
failing stage, concise root cause, useful path:line locations and whether a main-model
decision is required. Do not return raw logs.
```

### Fix example

```text
Run `make check`. Fix only mechanical formatting/lint/type issues without changing
behavior. Rerun the smallest useful checks and finish with the root check. Stop if an
architectural or behavioral decision is required.
```

## Result returned to Codex

```json
{
  "status": "failed",
  "summary": "Ruff formatting failed in two backend files.",
  "changed_files": [],
  "checks": {"make check": "failed"},
  "relevant_locations": ["backend/app/service.py:1"],
  "needs_main_model_decision": false,
  "decision_required": null
}
```

Raw stdout/stderr from OpenCode is captured inside the MCP process and is never returned
by default.

## Recommended standards rule

Add a project/organization rule similar to:

```text
Prefer free_worker.delegate_task for bounded execution loops: tests, lint, formatting,
type checks, builds, Docker/Compose validation, CI/GitHub inspection, large log
inspection, routine repository exploration and mechanical corrections.

Delegate a whole execution loop rather than each command separately.

Keep architecture, security, transaction/concurrency decisions, migration strategy,
deployment design, ambiguous behavior, public contracts and final acceptance on the
primary model.

Raw logs stay with the worker. Request raw output only when the compact result is
insufficient.
```

## Docker

The image contains both the MCP server and OpenCode:

```bash
docker build -t codex-free-worker .
```

For stdio MCP you can configure Codex to start Docker directly:

```toml
[mcp_servers.free_worker]
command = "docker"
args = [
  "run", "--rm", "-i",
  "-e", "OPENROUTER_API_KEY",
  "-v", "/home/YOU/Work:/home/YOU/Work",
  "codex-free-worker"
]
tool_timeout_sec = 900
```

The mount deliberately preserves the same absolute repository paths, because Codex passes
an absolute `cwd` to `delegate_task`.

Docker mode only contains generic `git`/`make` plus OpenCode. Delegated project checks may
need project runtimes, Docker CLI/socket, `gh`, or other tools that are already available on
your host. For that reason **native stdio is the recommended mode for development**.

## Security boundary

The bridge starts OpenCode through a fixed argument list and never uses `shell=True`.
The worker prompt forbids privilege escalation, destructive Git operations, merges,
production deployment, secret retrieval and unrelated edits.

This prompt is not an OS sandbox. Keep normal Codex/OpenCode permission controls enabled.

## Development

```bash
make fix
make check
```

Tests cover the fixed North Mini Code model, inspect/fix prompt boundaries, compact-result
extraction from noisy JSONL, refusal to forward raw logs, and OpenCode command construction.
