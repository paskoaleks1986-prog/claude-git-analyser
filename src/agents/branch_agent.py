"""Branch agent — pure git analysis, no Claude API calls."""
from __future__ import annotations

from datetime import datetime, timezone

from config import Config
from git.repo import BranchInfo, GitRepo


def _age_days(date_str: str) -> int:
    """Return days since given ISO date string."""
    try:
        # git dates look like: 2024-01-15 10:30:00 +0200
        dt = datetime.fromisoformat(date_str.replace(" ", "T", 1))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(tz=timezone.utc) - dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return 0


def run(repo: GitRepo, config: Config) -> dict:
    """Analyze all branches and return structured data."""
    main_branch = repo.get_main_branch()
    branches: list[BranchInfo] = repo.get_branches()

    result: list[dict] = []

    for b in branches:
        age = _age_days(b.last_commit_date)
        is_main = b.name == main_branch

        unmerged = 0 if is_main else repo.count_unmerged_commits(b.name, main_branch)

        # Status classification
        if is_main:
            status = "main"
            recommendation = "keep"
            issues: list[str] = []
        elif age > config.stale_branch_days and unmerged == 0:
            status = "stale"
            recommendation = "delete"
            issues = [f"No activity for {age} days and fully merged into {main_branch}"]
        elif age > config.stale_branch_days:
            status = "stale"
            recommendation = "merge_or_delete"
            issues = [f"No activity for {age} days, has {unmerged} unmerged commits"]
        elif unmerged > 30:
            status = "long_running"
            recommendation = "review"
            issues = [f"Long-running branch with {unmerged} unmerged commits"]
        else:
            status = "active"
            recommendation = "keep"
            issues = []

        result.append({
            "name": b.name,
            "last_commit_hash": b.last_commit_hash,
            "last_commit_date": b.last_commit_date,
            "author": b.author,
            "is_current": b.is_current,
            "age_days": age,
            "unmerged_commits": unmerged,
            "status": status,
            "recommendation": recommendation,
            "issues": issues,
        })

    # Summary counters
    summary = {
        "total": len(result),
        "main": sum(1 for b in result if b["status"] == "main"),
        "active": sum(1 for b in result if b["status"] == "active"),
        "stale": sum(1 for b in result if b["status"] == "stale"),
        "long_running": sum(1 for b in result if b["status"] == "long_running"),
    }

    return {
        "main_branch": main_branch,
        "summary": summary,
        "branches": result,
    }