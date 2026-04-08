"""Stack detector — identifies languages, frameworks, and services in the repo."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StackInfo:
    primary_language: str = "unknown"
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    lint_tools: list[str] = field(default_factory=list)
    test_tools: list[str] = field(default_factory=list)
    source_extensions: list[str] = field(default_factory=list)
    comment_prefix_map: dict[str, str] = field(default_factory=dict)
    ci_provider: str = "none"
    package_managers: list[str] = field(default_factory=list)


def detect(repo_path: Path) -> StackInfo:
    files = _list_files(repo_path)
    file_set = set(files)
    names = {Path(f).name.lower() for f in files}
    ext_count = _count_extensions(files)
    info = StackInfo()

    lang_rules = {
        "Python":     [".py"],
        "TypeScript": [".ts", ".tsx"],
        "JavaScript": [".js", ".jsx", ".mjs", ".cjs"],
        "Vue":        [".vue"],
        "Go":         [".go"],
        "Rust":       [".rs"],
        "Java":       [".java", ".kt"],
        "Ruby":       [".rb"],
        "PHP":        [".php"],
        "C/C++":      [".c", ".cpp", ".cc", ".h", ".hpp"],
    }
    lang_scores: dict[str, int] = {}
    for lang, exts in lang_rules.items():
        score = sum(ext_count.get(e, 0) for e in exts)
        if score > 0:
            lang_scores[lang] = score
    info.languages = sorted(lang_scores, key=lang_scores.__getitem__, reverse=True)
    info.primary_language = info.languages[0] if info.languages else "unknown"

    comment_map: dict[str, str] = {}
    source_exts: list[str] = []
    for lang in info.languages:
        for ext in lang_rules.get(lang, []):
            source_exts.append(ext)
            comment_map[ext] = "#" if lang == "Python" else "//"
    info.source_extensions = list(dict.fromkeys(source_exts))
    info.comment_prefix_map = comment_map

    fw: list[str] = []
    if _any_file(file_set, ["manage.py"]) or _content_has(repo_path, "from django", as_import=True) or _content_has(repo_path, "import django", as_import=True):
        fw.append("Django")
    if _content_has(repo_path, "from fastapi", as_import=True) or _content_has(repo_path, "import fastapi", as_import=True):
        fw.append("FastAPI")
    if _content_has(repo_path, "from flask", as_import=True) or _content_has(repo_path, "import flask", as_import=True):
        fw.append("Flask")

    pkg = _read_json(repo_path / "package.json")
    if pkg:
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "nuxt" in deps or "nuxt" in names or _any_file(file_set, ["nuxt.config.ts", "nuxt.config.js"]):
            fw.append("Nuxt")
        elif "vue" in deps or ".vue" in ext_count:
            fw.append("Vue")
        if "next" in deps or _any_file(file_set, ["next.config.js", "next.config.ts"]):
            fw.append("Next.js")
        if "react" in deps:
            fw.append("React")
        if "express" in deps:
            fw.append("Express")
        if "nestjs/core" in " ".join(deps) or _any_file(file_set, ["nest-cli.json"]):
            fw.append("NestJS")
    info.frameworks = fw

    svc: list[str] = []
    compose_content = _read_compose(repo_path)
    all_config_content = _read_config_files(repo_path)
    service_keywords = {
        "Postgres":  ["postgres", "postgresql", "pg:"],
        "Redis":     ["redis"],
        "RabbitMQ":  ["rabbitmq", "amqp"],
        "MongoDB":   ["mongo"],
        "MySQL":     ["mysql", "mariadb"],
        "Celery":    ["celery"],
        "Kafka":     ["kafka"],
        "Nginx":     ["nginx"],
    }
    search_content = (compose_content + all_config_content).lower()
    for service, keywords in service_keywords.items():
        if any(kw in search_content for kw in keywords):
            svc.append(service)
    info.services = svc

    pm: list[str] = []
    if _any_file(file_set, ["pyproject.toml", "requirements.txt", "setup.py"]):
        pm.append("pip")
    if _any_file(file_set, ["package.json"]):
        if _any_file(file_set, ["pnpm-lock.yaml"]):
            pm.append("pnpm")
        elif _any_file(file_set, ["yarn.lock"]):
            pm.append("yarn")
        else:
            pm.append("npm")
    info.package_managers = pm

    lint: list[str] = []
    if "Python" in info.languages:
        lint.append("ruff")
    if any(l in info.languages for l in ["JavaScript", "TypeScript", "Vue"]) or "Nuxt" in fw:
        lint.append("eslint")
    if _any_file(file_set, ["Dockerfile", "dockerfile"]):
        lint.append("hadolint")
    info.lint_tools = lint

    test: list[str] = []
    if "Python" in info.languages:
        test.append("pytest")
        test.append("pytest-cov")
    if pkg:
        deps_all = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "jest" in deps_all:
            test.append("jest")
        if "vitest" in deps_all:
            test.append("vitest")
        if not any(t in deps_all for t in ["jest", "vitest"]):
            if any(l in info.languages for l in ["JavaScript", "TypeScript", "Vue"]):
                test.append("vitest")
    info.test_tools = test

    if (repo_path / ".github" / "workflows").exists():
        info.ci_provider = "github_actions"
    elif _any_file(file_set, [".gitlab-ci.yml", ".gitlab-ci.yaml"]):
        info.ci_provider = "gitlab_ci"
    elif _any_file(file_set, ["Jenkinsfile"]):
        info.ci_provider = "jenkins"

    return info


_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".next", ".nuxt"}


def _list_files(path: Path, max_files: int = 2000) -> list[str]:
    result: list[str] = []
    try:
        for f in path.rglob("*"):
            if not f.is_file():
                continue
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            result.append(str(f.relative_to(path)))
            if len(result) >= max_files:
                break
    except (PermissionError, OSError):
        pass
    return result


def _count_extensions(files: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in files:
        ext = Path(f).suffix.lower()
        if ext:
            counts[ext] = counts.get(ext, 0) + 1
    return counts


def _any_file(file_set: set[str], names: list[str]) -> bool:
    return any(name.lower() in (f.lower() for f in file_set) for name in names)


def _content_has(repo_path: Path, keyword: str, as_import: bool = False) -> bool:
    """Search for keyword in project source files (excluding vendor dirs).

    When as_import=True the keyword must appear at line start (real import,
    not a string literal inside helper code like this file itself).
    """
    import re as _re
    pattern = _re.compile(
        rf"^{_re.escape(keyword)}\b", _re.MULTILINE | _re.IGNORECASE
    ) if as_import else None

    for ext in (".py", ".toml", ".cfg", ".ini"):
        for f in list(repo_path.rglob(f"*{ext}"))[:40]:
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            try:
                text = f.read_text(errors="ignore")
                if pattern:
                    if pattern.search(text):
                        return True
                else:
                    if keyword.lower() in text.lower():
                        return True
            except OSError:
                pass
    return False


def _read_json(path: Path) -> dict | None:
    try:
        import json
        return json.loads(path.read_text(errors="ignore"))
    except Exception:
        return None


def _read_compose(repo_path: Path) -> str:
    parts: list[str] = []
    for pattern in ["docker-compose*.yml", "docker-compose*.yaml"]:
        for f in repo_path.glob(pattern):
            try:
                parts.append(f.read_text(errors="ignore"))
            except OSError:
                pass
    return "\n".join(parts)


def _read_config_files(repo_path: Path) -> str:
    parts: list[str] = []
    for pattern in ["*.env*", "*.cfg", "*.ini", "*.toml", "*.conf"]:
        for f in list(repo_path.glob(pattern))[:5]:
            try:
                parts.append(f.read_text(errors="ignore"))
            except OSError:
                pass
    return "\n".join(parts)