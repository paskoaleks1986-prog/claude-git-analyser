# AGENT_HISTORY.md
# История развития проекта claude-git-analyser

Этот документ описывает три состояния проекта — от первой версии до текущего кода.
Он написан для агента: читай его перед тем как вносить любые изменения в репо.

---

## Состояние 0 — Исходный репо (точка отсчёта)

Структура которая была запушена первой:

```
src/
├── agents/
│   ├── branch_agent.py     — анализ веток через git
│   ├── commit_agent.py     — анализ коммитов через Claude (первая версия)
│   ├── quality_agent.py    — ruff + pytest (базовый, только Python)
│   └── release_agent.py    — итоговый score 0-100
├── ai/
│   ├── client.py           — обёртка над anthropic SDK, требовал ANTHROPIC_API_KEY
│   └── prompts.py          — два промпта: commit evolution + release readiness
├── git/
│   └── repo.py             — метаданные репо, коммиты, ветки
├── report/
│   ├── terminal.py         — Rich вывод
│   └── yaml_export.py      — YAML отчёт
├── cli.py                  — click CLI, флаг --api-key
├── config.py               — dataclass, поле api_key + ANTHROPIC_API_KEY
└── orchestrator.py         — линейный pipeline: branch → commit → quality → release
tests/
└── test_git_repo.py        — 30 тестов
.env                        — API ключ (был закоммичен — ошибка)
report.yaml                 — output файл (был закоммичен — ошибка)
install.sh
pyproject.toml              — зависимость anthropic>=0.25.0
README.MD
LINKEDIN_ARTICLE.md
```

**Как работало**: `ClaudeClient(api_key=ANTHROPIC_API_KEY)` → прямые вызовы Anthropic API.
Claude видел только сообщения коммитов, не реальный код.
Анализ шёл по плоскому списку коммитов без группировки.

**Проблемы**:
- API ключ закоммичен в `.env` — нужно убрать из истории или добавить в `.gitignore`
- `report.yaml` закоммичен — output не должен быть в репо
- Анализ по сообщениям коммитов слабый: если написано `feat: add auth` и там захардкожен пароль — инструмент это не видит
- Один стек (Python), нет мультистековой поддержки

---

## Состояние 1 — Переосмысление: коммиты → смысловые блоки

### Главное изменение идеи

Не "анализ каждого коммита" — а **анализ смысловых блоков развития**.

Коммиты — шум. Блок — единица смысла:
```
[commit 1-3]  gitignore + .env + docker  →  блок: инфраструктура
[commit 4-9]  auth модуль + тесты + фикс →  блок: auth
[commit 10-12] добавили Redis            →  блок: кеширование ← здесь упал перформанс
```

Claude теперь получает **реальный diff по блоку**, а не просто текст коммита.

### Новая структура (три блока)

```
BLOCK 1: Data Collection  — без Claude, чистый git + детект стека
BLOCK 2: Semantic Engine  — Claude читает реальные диффы
BLOCK 3: Synthesis        — динамика, кривая качества, релиз
```

### Что добавлено

**Новые файлы:**

`src/git/grouper.py`
- Предварительная группировка коммитов до Claude
- Три эвристики: паттерны файлов (dockerfile→infra, test_→testing, auth→auth), временной промежуток (>6h = новая сессия), смена intent
- Возвращает `DraftGroup[]` — черновые группы для Claude

`src/setup/stack_detector.py`
- `StackInfo` dataclass: языки, фреймворки, сервисы, инструменты, CI
- Python / JS / TS / Vue / Nuxt / Go / Rust / Java
- Django / FastAPI / Flask / Nuxt / Vue / Next.js / React / NestJS
- Postgres / Redis / RabbitMQ / MongoDB / Celery / Kafka / Nginx (из docker-compose)
- GitHub Actions / GitLab CI / Jenkins

`src/setup/tool_checker.py`
- Проверяет наличие ruff, eslint, pytest, jest/vitest
- Если инструмент отсутствует — **спрашивает** пользователя, не молчит
- Возвращает `ToolCheckResult` с флагами `available`, `user_declined`

`src/agents/block_analyzer.py`
- Заменяет `commit_agent.py` в пайплайне (старый файл оставлен, не используется)
- Claude получает: черновые группы + реальный diff каждого блока (≤3k chars) + дерево файлов
- Возвращает финальные блоки с `quality_score`, `architecture_impact`, `issues`, `verdict`

`src/agents/architecture_agent.py`
- Строит таймлайн архитектуры по блокам
- Детектирует drift: original intent vs current reality
- Указывает конкретный блок где архитектура "сломалась"

`src/agents/dynamic_analyzer.py`
- Кривая качества: `block1=8.0 → block3=3.4 → block4=8.0`
- Точки деградации/восстановления
- `harmful_blocks`: блоки которые принесли больше вреда чем пользы
- `best_blocks`: примерные блоки

**Обновлённые файлы:**

`src/git/repo.py`
- `get_block_diff(from_hash, to_hash, extensions, max_chars=3000)` — один diff на блок
- `get_file_tree_at(commit_hash)` — снапшот дерева файлов на любой точке истории
- `scan_inline_comments(comment_prefix_map)` — мультистековое сканирование TODO/FIXME/HACK

`src/agents/quality_agent.py`
- Мультистек: Python → ruff + pytest, JS/TS/Vue → eslint + jest/vitest
- Принимает `ToolCheckResult` — знает что доступно, не молчит если инструмент отсутствует

`src/agents/release_agent.py`
- Теперь принимает полный контекст: arch_data + dynamic_data + quality_data
- Recommendations с полем `effort: small | medium | large`

`src/ai/prompts.py`
- Полностью переписан: 4 промпта вместо 2
- `BLOCK_ANALYZER_*`, `ARCHITECTURE_AGENT_*`, `DYNAMIC_ANALYZER_*`, `RELEASE_READINESS_*`
- Все промпты требуют JSON-only output, без markdown, без пreamble

`src/report/terminal.py`
- Новые секции: `print_blocks()`, `print_architecture()`, `print_dynamics()`
- `print_header()` принимает frameworks + services
- Quality curve с ASCII баром: `████░░░░░░ 4.2`

`src/orchestrator.py`
- Переписан под 3-блочный sequential pipeline
- Каждый блок выводит промежуточный результат сразу

**Состояние тестов**: 49 тестов — добавлены grouper, stack_detector, tool_checker, новые методы git/repo.

**Транспорт**: ещё использует `anthropic` SDK + `ANTHROPIC_API_KEY` (изменится в состоянии 2).

---

## Состояние 2 — Отказ от Anthropic SDK: SDK + Subprocess

### Причина

Проект использует Claude Code. Прямые вызовы Anthropic API через `ANTHROPIC_API_KEY` несовместимы с этим окружением. Аутентификация через OAuth подписки, ключ не нужен.

### Аудит (что нашли перед изменениями)

```
src/ai/client.py     — import anthropic, anthropic.Anthropic(api_key=...)
src/config.py        — поле api_key, os.environ.get("ANTHROPIC_API_KEY")
pyproject.toml       — anthropic>=0.25.0
.env.example         — ANTHROPIC_API_KEY секция
tests/test_git_repo.py — 2 теста на ANTHROPIC_API_KEY
```

### Что изменилось

`src/ai/client.py` — полностью переписан, два транспорта:

```
ClaudeCodeClient       — claude-code-sdk, async → sync через asyncio.run()
                         OAuth через подписку Claude, без API ключа

ClaudeSubprocessClient — subprocess вызов `claude --print --output-format text`
                         Fallback когда SDK не установлен, нулевые зависимости

make_client()          — фабрика: пробует SDK, при ImportError → subprocess
```

Публичный интерфейс не изменился: `ask(system, user)` и `ask_json(system, user)`.
Все агенты работают без изменений.

`src/config.py`:
- Убрано поле `api_key`
- Убран `os.environ.get("ANTHROPIC_API_KEY")`
- Добавлено поле `claude_path: str = "claude"`
- `validate()` теперь проверяет `shutil.which(claude_path)`, не ключ

`src/cli.py`:
- Убран флаг `--api-key`
- Добавлен флаг `--claude-path` (путь к бинарю claude)

`src/orchestrator.py`:
- `ClaudeClient(api_key=config.api_key)` → `make_client(model=config.model, claude_path=config.claude_path)`

`pyproject.toml`:
- `anthropic>=0.25.0` → `claude-code-sdk>=0.0.3`

`install.sh`:
- Убрана проверка `ANTHROPIC_API_KEY`
- Добавлена проверка наличия `claude` CLI

`.gitignore` — добавлен (не было):
- `.env`, `report.yaml`, `.venv/`, `__pycache__/`, `coverage.json`

**Итог**: 0 упоминаний `anthropic` во всём проекте.

---

## Текущая структура репо

```
src/
├── agents/
│   ├── branch_agent.py        — чистый git, stale/active/long_running
│   ├── commit_agent.py        — v1, оставлен, в пайплайне не используется
│   ├── block_analyzer.py      — Block 2: Claude + реальные диффы
│   ├── architecture_agent.py  — Block 2: таймлайн + drift detection
│   ├── quality_agent.py       — Block 3: ruff/eslint + pytest/jest
│   ├── dynamic_analyzer.py    — Block 3: кривая качества, harmful blocks
│   └── release_agent.py       — Block 3: score 0-100
├── ai/
│   ├── client.py              — ClaudeCodeClient + ClaudeSubprocessClient + make_client()
│   └── prompts.py             — 4 промпта, JSON-only
├── git/
│   ├── repo.py                — git subprocess: commits, diffs, file trees, comments
│   └── grouper.py             — DraftGroup, group(), format_for_claude()
├── setup/
│   ├── __init__.py
│   ├── stack_detector.py      — StackInfo: языки, фреймворки, сервисы
│   └── tool_checker.py        — ToolCheckResult: спрашивает перед установкой
├── report/
│   ├── terminal.py            — Rich: blocks, arch, dynamics, quality curve
│   └── yaml_export.py         — YAML с meta секцией
├── cli.py                     — click: --claude-path, --no-interactive
├── config.py                  — claude_path, non_interactive (нет api_key)
└── orchestrator.py            — 3-блочный sequential pipeline
tests/
└── test_git_repo.py           — 49 тестов
.gitignore
install.sh
pyproject.toml                 — claude-code-sdk>=0.0.3
```

---

## Ключевые архитектурные решения

**Импорты**: модули импортируются напрямую без пакетного префикса.
Пример: `from git.repo import GitRepo`, `from agents import branch_agent`, `from ai.client import make_client`.

**Токены**: Claude никогда не читает полные файлы. Только `git diff` по блоку (≤3k chars) и `git ls-tree` снапшоты.

**Два вызова Claude на весь пайплайн Block 2**: `block_analyzer` + `architecture_agent`.
Два вызова на Block 3: `dynamic_analyzer` + `release_agent`.

**JSON-only промпты**: все четыре промпта требуют чистый JSON без markdown.
`_extract_json()` в `ai/client.py` снимает fence-обёртки если модель их добавит.

**tool_checker никогда не молчит**: если инструмент отсутствует — спрашивает.
`non_interactive=True` (флаг `--no-interactive`) пропускает все вопросы — для CI.

**Транспорт**: `make_client()` выбирает сам — SDK если установлен, subprocess если нет.
Оба транспорта имеют одинаковый интерфейс, агенты не знают какой используется.

---

## Что НЕ трогать

- `commit_agent.py` — не удалять, оставлен как v1 артефакт
- `yaml_export.py` — не менять схему, `meta` секция обязательна
- `branch_agent.py` — без изменений, чистый git без Claude
- Сигнатуры всех публичных функций агентов — они жёстко связаны через orchestrator

---

## Что ещё нужно сделать

- Удалить `.env` из истории git (или хотя бы из текущего индекса): `git rm --cached .env`
- Удалить `report.yaml` из репо: `git rm report.yaml`
- Добавить `.python-version` файл для pyenv: `echo "3.11" > .python-version`
- README.MD переименовать в README.md (регистр имеет значение на Linux)

---

## Состояние 3 — Аудит и исправление веб-агента (claude-sonnet-4-6 в Claude Code)

### Причина

Код Состояния 2 был написан в веб-агенте. При генерации несколько файлов оказались
сломаны или не обновлены до финального состояния. Запуск тестов показал 0 из 41 пройденных.

### Что было сломано

**Критические баги:**

1. `src/git/repo.py` — файл был продублирован сам в себя: первые 24 строки — обрванный
   первый экземпляр, строки 25-688 — полный второй. Результат: `IndentationError` при импорте.

2. `src/git/stack_detector.py` и `src/git/tool_checker.py` — файлы лежали в неправильной
   директории. Веб-агент создал их в `src/git/`, хотя весь код (orchestrator, агенты, тесты)
   ожидал их в `src/setup/`. Результат: `ModuleNotFoundError`.

3. `src/agents/branch_agent.py` — импорты `from checker.config import Config` и
   `from checker.git.repo import ...`. Пакета `checker` не существует. Результат: `ImportError`.

4. `src/ai/client.py` — не был обновлён до Состояния 2. Содержал старый код с
   `import anthropic` и `ClaudeClient(api_key=...)` вместо `ClaudeCodeClient` + `ClaudeSubprocessClient`.

5. `src/orchestrator.py` — не обновлён: `from ai.client import ClaudeClient` и
   `ClaudeClient(api_key=config.api_key, ...)` вместо `make_client(...)`.

6. `pyproject.toml` — зависимость `claude-code-sdk>=0.0.3` была заменена на `anthropic>=0.40.0`
   (ошибка при аудите, т.к. `AGENT_HISTORY.md` не был прочитан заранее). Откатано обратно.

7. `ClaudeClient` не экспортировался из нового `ai/client.py`. Все четыре агента используют
   его как тайп-хинт — добавлен алиас `ClaudeClient = ClaudeCodeClient | ClaudeSubprocessClient`.

8. Все файлы содержали артефакт веб-агента `# python:путь/к/файлу` в первой строке — убраны.

### Что изменилось

- `src/git/repo.py` — убран дублирующий фрагмент, восстановлен чистый файл
- `src/git/stack_detector.py` и `src/git/tool_checker.py` — удалены из `git/`
- `src/setup/stack_detector.py` и `src/setup/tool_checker.py` — созданы в правильной директории
- `src/agents/branch_agent.py` — исправлены импорты
- `src/ai/client.py` — полностью переписан: `ClaudeCodeClient`, `ClaudeSubprocessClient`, `make_client()`, алиас `ClaudeClient`
- `src/orchestrator.py` — обновлён на `make_client()`
- Все `# python:...` артефакты убраны из всех файлов

### Результат

```
41 passed in 0.49s
```

Все модули импортируются без ошибок. Пайплайн готов к запуску на реальном репозитории.

### Урок

Перед любыми изменениями читать `AGENT_HISTORY.md`. Веб-агенты часто:
- кладут файлы не в ту директорию (путь в комментарии `# python:...` — подсказка где файл должен быть)
- не завершают рефакторинг до конца (несколько файлов остаются на старом коде)
- дублируют содержимое файлов при генерации больших блоков