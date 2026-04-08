"""Commit pre-grouper — heuristic grouping before Claude semantic analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from git.repo import CommitInfo


@dataclass
class DraftGroup:
    id: int
    commits: list[CommitInfo]
    hint: str
    file_patterns: list[str] = field(default_factory=list)

    @property
    def first_hash(self) -> str:
        return self.commits[0].hash if self.commits else ""

    @property
    def last_hash(self) -> str:
        return self.commits[-1].hash if self.commits else ""

    @property
    def total_insertions(self) -> int:
        return sum(c.insertions for c in self.commits)

    @property
    def total_deletions(self) -> int:
        return sum(c.deletions for c in self.commits)

    @property
    def total_files(self) -> int:
        return sum(c.files_changed for c in self.commits)


_PATTERN_HINTS: list[tuple[list[str], str]] = [
    (["dockerfile", "docker-compose", ".env", ".gitignore", "makefile",
      "ci", "workflow", "gitlab-ci", "nginx", "gunicorn"], "infrastructure"),
    (["migration", "alembic", "schema", "seed", "fixture",
      "models.py", "model.py", "entity"], "database"),
    (["auth", "jwt", "token", "login", "register", "password",
      "permission", "role", "user", "oauth"], "auth"),
    (["test_", "_test", "spec.", "conftest", "__tests__", "fixtures",
      "mock", "factory"], "testing"),
    (["readme", "changelog", "docs/", "openapi", "swagger",
      ".md", "license"], "documentation"),
    (["config", "settings", "constants", "env", "pyproject",
      "package.json", "tsconfig"], "configuration"),
    (["router", "routes", "api", "endpoint", "view", "controller",
      "handler", "middleware"], "api"),
    (["component", ".vue", ".jsx", ".tsx", "page", "layout",
      "store", "composable", "hook", "style", ".css", ".scss"], "frontend"),
    (["service", "client", "integration", "redis", "celery",
      "rabbitmq", "kafka", "s3", "email", "smtp"], "services"),
]


def _parse_commit_date(date_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(date_str.replace(" ", "T", 1))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.now(tz=timezone.utc)


def _dominant_hint(messages: list[str], touched_files_hint: str = "") -> str:
    combined = " ".join(messages).lower() + " " + touched_files_hint.lower()
    scores: dict[str, int] = {}
    for patterns, hint in _PATTERN_HINTS:
        score = sum(1 for p in patterns if p in combined)
        if score > 0:
            scores[hint] = scores.get(hint, 0) + score
    if not scores:
        for msg in messages:
            msg_lower = msg.lower()
            if msg_lower.startswith("feat"):
                return "feature"
            if msg_lower.startswith("fix"):
                return "bugfix"
            if msg_lower.startswith("refactor"):
                return "refactor"
            if msg_lower.startswith("chore"):
                return "maintenance"
        return "mixed"
    return max(scores, key=scores.__getitem__)


def _time_gap_hours(a: CommitInfo, b: CommitInfo) -> float:
    da = _parse_commit_date(a.date)
    db = _parse_commit_date(b.date)
    return abs((db - da).total_seconds()) / 3600


def group(commits: list[CommitInfo], max_group_size: int = 12) -> list[DraftGroup]:
    if not commits:
        return []
    groups: list[DraftGroup] = []
    current: list[CommitInfo] = [commits[0]]
    current_hint = _dominant_hint([commits[0].message])
    for i in range(1, len(commits)):
        prev = commits[i - 1]
        curr = commits[i]
        gap = _time_gap_hours(prev, curr)
        new_hint = _dominant_hint([curr.message])
        start_new = False
        if len(current) >= max_group_size:
            start_new = True
        elif gap > 6.0:
            start_new = True
        elif new_hint != current_hint and new_hint != "mixed" and current_hint != "mixed":
            start_new = True
        if start_new:
            hint = _dominant_hint([c.message for c in current])
            groups.append(DraftGroup(id=len(groups) + 1, commits=current[:], hint=hint))
            current = [curr]
            current_hint = new_hint
        else:
            current.append(curr)
            current_hint = _dominant_hint([c.message for c in current])
    if current:
        hint = _dominant_hint([c.message for c in current])
        groups.append(DraftGroup(id=len(groups) + 1, commits=current[:], hint=hint))
    return groups


def format_for_claude(groups: list[DraftGroup]) -> str:
    lines: list[str] = []
    for g in groups:
        lines.append(f"\n--- DRAFT GROUP {g.id} (hint: {g.hint}) ---")
        lines.append(
            f"Commits: {len(g.commits)}  "
            f"+{g.total_insertions}/-{g.total_deletions} lines  "
            f"{g.total_files} files touched"
        )
        for c in g.commits:
            lines.append(f"  {c.short_hash} | {c.date[:10]} | {c.message[:80]}")
    return "\n".join(lines)