[English](README.md) | [Русский](README.ru.md)

# Codex Free Worker

Локальный MCP-мост, который позволяет Codex делегировать ограниченные циклы выполнения
в OpenCode.

Worker удерживает сырые логи тестов, сборки и CI вне контекста основной модели. OpenCode
сам анализирует вывод команд, может выполнять ограниченные циклы работы и возвращает
Codex только компактный структурированный результат.

Модель OpenCode выбирается во время запуска через `FREE_WORKER_MODEL`; репозиторий не
привязан к конкретной модели.

## Разделение ответственности

Используйте worker, когда делегирование заметно экономит контекст основной модели или
убирает повторяющиеся циклы запуска и диагностики.

Подходящие задачи:

- падающие test suites с большим выводом;
- анализ CI/GitHub Actions и других больших логов;
- ошибки Docker/Compose/build;
- циклы `run -> diagnose -> mechanical fix -> rerun`;
- большой поиск по репозиторию и рутинное исследование;
- ограниченные повторяющиеся или механические рефакторинги;
- validation workflow, где нужно выполнить несколько команд до получения краткого вывода.

Оставляйте на основной модели:

- архитектуру и публичные контракты;
- решения по security;
- стратегию migrations/persistence;
- concurrency/transaction design;
- deployment design;
- неоднозначное поведение;
- финальный review и acceptance.

Маленькие детерминированные команды с коротким выводом обычно дешевле запускать прямо
из Codex. Например: `git status`, `git diff --stat` или короткий успешный
`make check`.

**Делегируйте worker'у целые bounded execution loops, а не отдельные команды.**

## Требования

- Python 3.11+
- OpenCode, доступный как `opencode`
- настроенный provider/model для OpenCode
- Codex CLI с поддержкой stdio MCP

Worker запускает OpenCode неинтерактивно через `opencode run`, `--auto`, `--dir`,
`--model` и `--format json`.

## Быстрый старт: native install (рекомендуется)

Native-режим проще всего для разработки, потому что OpenCode получает те же пути
репозиториев и host tooling, что и Codex.

```bash
git clone https://github.com/DanilFaritovich/codex-free-worker-mcp.git
cd codex-free-worker-mcp

python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make check
```

Если окружение было создано инструментом, который не устанавливает `pip`, сначала
установите/инициализируйте `pip`.

Отдельно проверьте OpenCode с той же моделью, которую будете использовать в worker:

```bash
export FREE_WORKER_MODEL="provider/model"

opencode run \
  --auto \
  --dir "$PWD" \
  --model "$FREE_WORKER_MODEL" \
  --format json \
  "Reply with OK"
```

## Авторизация provider

Сам worker не управляет credentials provider'а. OpenCode уже должен уметь использовать
настроенную модель.

Если OpenCode авторизован через собственную конфигурацию provider'а, дополнительный
секрет в MCP-блоке не нужен.

Если provider ожидает переменную окружения, экспортируйте её в shell, из которого
запускается Codex, и разрешите передачу этой переменной в stdio MCP. Например, для
OpenRouter:

```bash
export OPENROUTER_API_KEY="..."
```

```toml
[mcp_servers.free_worker]
env_vars = ["OPENROUTER_API_KEY"]
```

Не храните provider secrets в репозитории или примерах конфигурации.

Локальный `.env` проекта **не загружается этим native MCP автоматически**.
`.env.example` только документирует поддерживаемые переменные. Реальные credentials
передавайте через shell, secret manager, конфигурацию provider'а OpenCode или forwarding
переменных окружения Codex MCP.

## Подключение к Codex

Добавьте MCP server в `~/.codex/config.toml`, используя абсолютные пути:

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
FREE_WORKER_MODEL = "provider/model"
FREE_WORKER_OPENCODE_BIN = "/absolute/path/to/opencode"
FREE_WORKER_ALLOWED_ROOTS = "/home/YOU/Work"
FREE_WORKER_TIMEOUT_SECONDS = "840"
FREE_WORKER_MAX_RESULT_CHARS = "8000"
```

`FREE_WORKER_OPENCODE_BIN` можно не указывать, если `opencode` уже доступен в
`PATH` MCP-процесса. Чтобы узнать host path:

```bash
which opencode
```

После изменения конфигурации перезапустите Codex и проверьте сервер:

```bash
codex mcp list
```

После первых тестов можно автоматически разрешить read-only inspection и оставить
подтверждение для задач, способных менять файлы:

```toml
[mcp_servers.free_worker.tools.inspect_task]
approval_mode = "approve"

[mcp_servers.free_worker.tools.fix_task]
approval_mode = "prompt"
```

Для первого запуска нормально оставить оба инструмента в режиме `prompt`.

## MCP tools

Сервер публикует два инструмента с разным назначением:

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

`inspect_task` предназначен для validation, диагностики логов, CI/build inspection и
большого рутинного исследования. Worker получает инструкцию не изменять файлы
репозитория.

`fix_task` разрешает только ограниченные механические изменения, когда ожидаемое
поведение уже определено. Архитектура, security, persistence, migration policy,
concurrency, deployment design, публичные контракты, неоднозначное поведение и финальный
acceptance остаются на основной модели Codex.

Оба инструмента требуют, чтобы `cwd` после resolve находился внутри одного из абсолютных
путей `FREE_WORKER_ALLOWED_ROOTS`. Проверка выполняется после разрешения symlink.

### Пример inspect

```text
Run the repository validation workflow. Do not modify files.
If it fails, identify only the meaningful failing stage, concise root cause, useful
path:line locations, and whether a primary-model decision is required.
Do not return raw logs.
```

### Пример fix

```text
Run the repository validation workflow.
Fix only bounded mechanical formatting/lint/type/test issues without changing intended
behavior. Rerun the smallest useful checks, then the project-level validation.
Stop if an architectural or behavioral decision is required.
```

## Результат, возвращаемый Codex

Пример:

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

JSONL stdout OpenCode обрабатывается потоково. Tool/log events отбрасываются вместо
накопления в памяти, а bridge сохраняет только компактный marked result из
несинтетического OpenCode `text` event. stderr отбрасывается и не передаётся Codex.

Статусы:

- `passed` — делегированная работа завершилась без изменений;
- `fixed` — выполнены ограниченные изменения и validation прошла;
- `failed` — worker или делегированная validation завершились ошибкой;
- `blocked` — для продолжения требуется решение основной модели.

## Интеграция с Codex

MCP server публикует общие правила делегирования через MCP server instructions. Когда
сервер подключён, Codex получает эти правила вместе с описаниями двух tools. Если сервер
недоступен и `required = false`, Codex продолжает работу без worker.

Server instructions специально остаются generic:

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

Project skills не должны знать об OpenCode, конкретном provider или модели. Выбор модели
остаётся host/runtime настройкой через `FREE_WORKER_MODEL`.

### Использование с codex-development-standards

Этот MCP — host-level infrastructure. Application repositories не должны напрямую
зависеть от этого репозитория.

Если вы используете
[`codex-development-standards`](https://github.com/DanilFaritovich/codex-development-standards),
его task-development workflow может определять, **когда** следует использовать доступный
optional execution worker. Standards синхронизируются в каждый проект отдельно, а MCP
настраивается один раз в пользовательской конфигурации Codex.

Предполагаемые слои:

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

Так проекты остаются переносимыми:

- если MCP доступен, Codex может делегировать подходящие bounded execution loops;
- если MCP недоступен и `required = false`, Codex работает напрямую;
- project instructions не должны знать provider/model OpenCode;
- Git delivery и финальный acceptance остаются у основной модели Codex.

Для более активного автоматического использования во всех локальных репозиториях можно
добавить короткое optional правило в глобальный `~/.codex/AGENTS.md`:

```text
When free_worker MCP tools are available, prefer them for bounded high-output execution
loops or repeated mechanical run/diagnose/fix/rerun work. If unavailable, continue
directly without treating their absence as an error. Keep design decisions and final
review on the primary model.
```

Не копируйте это правило в каждый проект, если проекту не нужна отдельная delegation
policy.

### Рекомендуемый workflow интеграции

1. Установить worker нативно и проверить OpenCode с выбранной моделью.
2. Настроить `free_worker` глобально в Codex с `required = false`.
3. Ограничить `FREE_WORKER_ALLOWED_ROOTS` минимально необходимым development root.
4. Перезапустить Codex и проверить сервер через `codex mcp list`.
5. Делегировать project-owned validation entry points: `make check`, `make verify`
   или эквивалентные команды.
6. Worker анализирует raw output и выполняет внутренние итерации; основная модель
   проверяет компактный `WorkerResult` и resulting diff.
7. Если `needs_main_model_decision=true` или результата недостаточно, вернуть задачу
   основной модели.
8. Commit planning, staging, commits, push, PR delivery и финальный acceptance оставить
   основной модели Codex.

Первый тест интеграции:

```text
Use free_worker.inspect_task.
Run the repository validation command.
Do not modify files and do not run the command yourself.
Return only the compact worker result.
```

## Troubleshooting

### Codex не показывает сервер

```bash
codex mcp list
```

Проверьте, что `command` и `cwd` заданы абсолютными путями, затем полностью
перезапустите Codex после изменения `~/.codex/config.toml`.

### OpenCode не найден

```bash
which opencode
```

Укажите этот абсолютный путь в `FREE_WORKER_OPENCODE_BIN` или убедитесь, что
`opencode` доступен в окружении MCP-процесса.

### `cwd is outside FREE_WORKER_ALLOWED_ROOTS`

Добавьте минимальный родительский каталог, внутри которого разрешена делегированная
работа. Worker сначала разрешает symlink и только потом проверяет boundary.

### Worker возвращает `failed`

Сначала запустите OpenCode напрямую с настроенной моделью. Если provider требует
авторизацию, проверьте её отдельно от MCP.

Bridge специально не возвращает Codex raw stderr и большие логи. Для диагностики
provider/runtime при необходимости запускайте OpenCode напрямую.

## Docker

Образ содержит MCP server и OpenCode:

```bash
docker build -t codex-free-worker .
```

Codex может запускать Docker напрямую как stdio MCP:

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

Mount сохраняет те же абсолютные пути репозиториев, потому что Codex передаёт worker
абсолютный `cwd`. Этот путь также должен входить в `FREE_WORKER_ALLOWED_ROOTS`.

Docker mode содержит только generic tooling и OpenCode. Делегированные project checks
могут требовать project runtimes, Docker CLI/socket, `gh` и другие host tools. Поэтому
для разработки **рекомендуется native stdio**.

## Security boundary

Bridge запускает OpenCode фиксированным списком аргументов и не использует
`shell=True`.

OpenCode запускается с `--auto`, чтобы worker мог выполнять разрешённые действия без
интерактивного approval. До запуска bridge разрешает `cwd` и отклоняет репозитории вне
`FREE_WORKER_ALLOWED_ROOTS`. Worker prompt запрещает privilege escalation, изменение
Git index/refs/history, commits, pushes, branch/tag mutation, production deployment,
получение secrets и unrelated edits.

Эти ограничения не являются OS sandbox. `inspect_task` — instruction-level read-only
boundary, поэтому оставляйте обычные Codex/OpenCode permission controls включёнными и не
передавайте secrets или production credentials недоверенной модели/provider. После
любого delegated fix основная модель Codex должна проверить working-tree diff.

## Разработка

```bash
make fix
make check
```

Тесты покрывают allowed-root configuration, границы server/tool delegation, policy
inspect/fix prompts, spoof-resistant extraction компактного результата, большой
потоковый JSONL, запрет передачи raw logs и построение команды OpenCode.
