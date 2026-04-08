# claude-check-repo

AI-powered repository evolution analyzer. Анализирует git-историю по смысловым блокам, строит таймлайн архитектуры, запускает проверки качества кода и выдаёт оценку готовности к релизу — на основе Claude.

Аутентификация через подписку Claude (OAuth) — **API-ключ не нужен**.

---

## Описание

Инструмент запускается из терминала как обычная CLI-утилита. Не требует сервера, базы данных или постоянно запущенного процесса. Ты указываешь путь к любому git-репозиторию на своей машине — инструмент анализирует его и выдаёт отчёт.

### Как это работает

Пайплайн состоит из трёх последовательных блоков:

**BLOCK 1 — Data Collection** *(без Claude, чистый Python + git)*

| Компонент | Файл | Что делает |
|---|---|---|
| Stack Detector | `src/setup/stack_detector.py` | Определяет языки, фреймворки (Django/FastAPI/Nuxt/NestJS/…), сервисы (Postgres/Redis/…), CI/CD. Читает файловую структуру и docker-compose |
| Git Repo | `src/git/repo.py` | Загружает коммиты с полной статистикой, ветки, дерево файлов, inline-комментарии (TODO/FIXME/HACK), файлы окружения |
| Grouper | `src/git/grouper.py` | Эвристически группирует коммиты в черновые блоки по временным паузам (>6ч), паттернам файлов и сообщениям. Готовит данные для Claude |
| Branch Agent | `src/agents/branch_agent.py` | Классифицирует ветки: main / active / stale / long_running. Считает возраст и число незамёрженных коммитов |
| Tool Checker | `src/setup/tool_checker.py` | Проверяет наличие ruff/eslint/pytest/jest. Если инструмент отсутствует — спрашивает перед запуском. Флаг `--no-interactive` пропускает вопросы |

**BLOCK 2 — Semantic Engine** *(2 вызова Claude)*

| Агент | Файл | Промпт | Что делает |
|---|---|---|---|
| Block Analyzer | `src/agents/block_analyzer.py` | `BLOCK_ANALYZER_*` в `prompts.py` | Получает черновые группы + реальные git-диффы (≤3k символов на блок). Финализирует группировку, называет блоки, выставляет `quality_score` (0–10) и `architecture_impact` (low/medium/high/breaking) |
| Architecture Agent | `src/agents/architecture_agent.py` | `ARCHITECTURE_AGENT_*` в `prompts.py` | Строит таймлайн архитектурных состояний по блокам. Детектирует drift: сравнивает исходный замысел с текущей реальностью, указывает блок где архитектура начала деградировать |

**BLOCK 3 — Synthesis** *(2 вызова Claude + локальные инструменты)*

| Компонент | Файл | Промпт | Что делает |
|---|---|---|---|
| Quality Agent | `src/agents/quality_agent.py` | — | Запускает ruff/eslint (парсит JSON-вывод), pytest/jest (собирает coverage), сканирует TODO/FIXME/HACK |
| Dynamic Analyzer | `src/agents/dynamic_analyzer.py` | `DYNAMIC_ANALYZER_*` в `prompts.py` | Строит кривую качества по блокам, находит точки деградации/восстановления, выделяет harmful_blocks и best_blocks |
| Release Agent | `src/agents/release_agent.py` | `RELEASE_READINESS_*` в `prompts.py` | Финальная оценка 0–100. Формирует список blockers, warnings, recommendations с приоритетами и оценкой усилий |

### Промпты

Все промпты находятся в `src/ai/prompts.py`. Каждый состоит из пары `*_SYSTEM` (роль и правила) + `*_USER` (шаблон с данными). Все четыре требуют от Claude **чистый JSON без markdown**.

| Константа | Назначение | Ключевые поля в ответе |
|---|---|---|
| `BLOCK_ANALYZER_SYSTEM/USER` | Семантический анализ коммитов | `blocks[].quality_score`, `architecture_impact`, `issues`, `verdict` |
| `ARCHITECTURE_AGENT_SYSTEM/USER` | Таймлайн + drift detection | `timeline`, `drift.detected`, `drift.drift_started_at_block`, `overall_health` |
| `DYNAMIC_ANALYZER_SYSTEM/USER` | Кривая качества | `quality_curve`, `inflection_points`, `harmful_blocks`, `best_blocks` |
| `RELEASE_READINESS_SYSTEM/USER` | Финальный score | `score` (0–100), `status`, `blockers`, `warnings`, `recommendations` |

Чтобы поменять логику анализа — редактируй промпты в `prompts.py`. Структура JSON-ответа задана прямо в тексте промпта.

### Транспорт Claude

`src/ai/client.py` содержит два транспорта с одинаковым интерфейсом (`ask` / `ask_json`):

- **`ClaudeCodeClient`** — использует `claude-code-sdk`, OAuth через подписку. Приоритетный.
- **`ClaudeSubprocessClient`** — вызывает `claude --print` через subprocess. Fallback если SDK недоступен или вернул ошибку.

`make_client()` выбирает транспорт автоматически. Агенты не знают какой используется.

---

## Установка

**Требования:**
- Python 3.11+
- `git` в PATH
- [Claude Code CLI](https://claude.ai/code) — установлен и авторизован через подписку

```bash
# 1. Клонировать репозиторий утилиты
git clone <repo-url>
cd claude-check-repo

# 2. Создать и активировать виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows

# 3. Установить утилиту
pip install -e .

# Проверить установку
claude-check-repo --help
```

Либо через скрипт (проверяет все зависимости автоматически):

```bash
bash install.sh
```

**После установки утилита доступна в терминале как `claude-check-repo` — venv активировать при каждом запуске не нужно**, если установлено через `pip install -e .` в активированном окружении.

### Опциональные инструменты

Нужны только в том репозитории, который ты анализируешь. Инструмент сам спросит при запуске если они не найдены:

```bash
pip install ruff pytest pytest-cov   # Python-проекты
npm install -g eslint                # JavaScript / TypeScript проекты
```

---

## Использование

Инструмент запускается из любой директории — путь к анализируемому репо передаётся аргументом:

```bash
# Анализировать конкретный репозиторий
claude-check-repo ./path/to/your-repo

# Анализировать текущую директорию
claude-check-repo

# Сохранить отчёт в файл
claude-check-repo ./repo --output report.yaml

# Ограничить глубину анализа (последние N коммитов)
claude-check-repo ./repo --max-commits 50

# CI-режим — без интерактивных вопросов об установке инструментов
claude-check-repo ./repo --no-interactive

# Указать путь к claude CLI вручную (если не в PATH)
claude-check-repo ./repo --claude-path /usr/local/bin/claude
```

**Флаги:**

| Флаг | По умолчанию | Описание |
|---|---|---|
| `--output` / `-o` | `repo_analysis.yaml` | Путь для сохранения YAML-отчёта |
| `--model` / `-m` | `claude-opus-4-5` | Модель Claude |
| `--max-commits` | `100` | Максимум коммитов для анализа |
| `--stale-days` | `30` | Через сколько дней ветка считается устаревшей |
| `--claude-path` | `claude` | Путь к бинарю claude CLI |
| `--no-interactive` | `false` | Пропустить вопросы об установке инструментов |

---

## Пример вывода

```
claude-check-repo ./my-project
```

```
━━━  BLOCK 1: Data Collection  ━━━

  Repository: my-project
  Language:   Python   Frameworks: FastAPI
  Services:  Postgres, Redis
  Remote:    github.com/user/my-project

  Total: 3  Active: 1  Stale: 1  Long-running: 1
  ● master   main    0d    0    keep
  ● feature  active  12d   8    keep
  ● old-api  stale   45d   0    delete

━━━  BLOCK 2: Semantic Engine  ━━━

  18 commits → 4 semantic blocks

  Block 1  INFRASTRUCTURE SETUP   7.5/10  impact=low    (3 commits)
  Block 2  AUTH MODULE             6.0/10  impact=high   (6 commits)
  Block 3  CACHING LAYER          3.4/10  impact=high   (5 commits)
    ⚠ Redis добавлен без инвалидации кэша
  Block 4  STABILISATION          8.0/10  impact=low    (4 commits)

  Overall health: DEGRADED
  ⚠ Architecture Drift (from block 3)
  Business logic просочилась в cache layer

━━━  BLOCK 3: Synthesis  ━━━

  ✓ ruff: PASSED
  ✓ Tests (pytest): 24 passed / 0 failed  coverage: 61.0%
  ⚠ Comments: 3 TODO  2 FIXME  1 HACK/XXX

  ┌──────────────────────────────────────────┐
  │ Score: 64/100   ALMOST READY ⚠          │
  │ Cache layer requires review before       │
  │ production deployment.                   │
  └──────────────────────────────────────────┘

  Blockers:
    ✗ Architecture drift in cache layer not resolved

  Recommendations:
    [HIGH] architecture — Extract cache invalidation to service layer (medium)
    [MEDIUM] testing — Increase coverage to 80%+ (medium)

  Report saved: repo_analysis.yaml
```

YAML-отчёт содержит полную структуру: `repository`, `branches`, `commit_evolution`, `architecture`, `code_quality`, `dynamics`, `release_readiness`, `environment`.
