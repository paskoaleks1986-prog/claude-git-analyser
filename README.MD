# 1. Забрать проект
git clone ... && cd claude-check-repo

# 2. Установить
bash install.sh
# или: pip install -e .

# 3. Ключ
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Опциональные инструменты в целевом репо
pip install ruff pytest pytest-cov

# 5. Запустить
claude-check-repo ./твой-проект
claude-check-repo ./твой-проект --output report.yaml --max-commits 50

Ключевые решения

Claude вызывается только 2 раза — commit evolution + release readiness. Всё остальное чистый Python
Никаких gitpython — только subprocess + git CLI, ноль лишних зависимостей
JSON всегда — промпты требуют чистый JSON, client.py вырезает markdown-обёртки если модель их добавит
Последовательный pipeline — данные текут от агента к агенту, каждый следующий получает контекст предыдущего

# claude-check-repo

**AI-powered repository evolution analyzer.** Analyzes your git history commit-by-commit, identifies development phases, runs code quality checks, and produces a release readiness report — powered by Claude.

## What it does

- **Commit Evolution** — groups commits into phases (architecture → features → refactor → stabilization), scores each commit, detects unnecessary commits and architecture drift
- **Branch Analysis** — identifies stale, orphan, and long-running branches
- **Code Quality** — runs `ruff` linter and `pytest` with coverage
- **Inline Comment Scan** — finds TODO/FIXME/HACK comments in your code
- **Release Readiness** — scores your repo 0–100 with specific blockers and recommendations

## Quick start

```bash
# 1. Install
pip install -e .

# 2. Set your API key
export ANTHROPIC_API_KEY=your_key_here

# 3. Run
claude-check-repo ./your-project
```

## Usage

```bash
# Analyze current directory
claude-check-repo

# Analyze specific repo
claude-check-repo ./path/to/repo

# Custom output file, limit commits
claude-check-repo ./repo --output report.yaml --max-commits 50

# Deep analysis (more tokens, more detail)
claude-check-repo ./repo --deep

# All options
claude-check-repo --help
```

## Output

Terminal output (Rich) + YAML report file:

```
claude-check-repo/
├── Branches (status, age, recommendations)
├── Commit Evolution (phases, scores, unnecessary commits, architecture drift)
├── Code Quality (ruff, pytest, inline comments)
└── Release Readiness (score 0-100, blockers, recommendations)
```

## Analytics tree (YAML schema)

```yaml
repository:
  name, language, framework, total_commits, remote_url

branches:
  main_branch, summary, branches[]
    - name, status, age_days, unmerged_commits, recommendation

commit_evolution:
  phases[]
    - id, name, commits[], quality_score, summary
  commits[]
    - hash, message, stats{files, +ins, -del}
    - ai_analysis{type, necessary, reasoning, issues, quality_score}
  architecture_drift{detected, description}

code_quality:
  linter{tool, passed, errors, warnings}
  tests{framework, total, passed, failed, coverage}
  inline_comments{todos[], fixmes[], personal[]}

release_readiness:
  score(0-100), status, blockers[], warnings[], recommendations[]
```

## Requirements

- Python 3.11+
- `ANTHROPIC_API_KEY` env variable
- `git` in PATH
- Optional: `ruff` (linting), `pytest` + `pytest-cov` (testing)

## Install dev tools in target repo

```bash
pip install ruff pytest pytest-cov
```