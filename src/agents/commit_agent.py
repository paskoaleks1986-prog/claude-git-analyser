"""Commit agent — analyzes commit evolution using Claude.

Sends only structured metadata (no full diffs) to keep token usage low.
"""
from __future__ import annotations

from checker.ai.client import ClaudeClient
from checker.ai.prompts import COMMIT_EVOLUTION_SYSTEM, COMMIT_EVOLUTION_USER
from checker.config import Config
from checker.git.repo import CommitInfo, GitRepo


def _format_commit_list(commits: list[CommitInfo]) -> str:
    lines: list[str] = []
    for i, c in enumerate(commits, 1):
        date_short = c.date[:10]
        lines.append(
            f"{i:>3}. {c.hash} | {date_short} | {c.message[:72]} "
            f"| files:{c.files_changed} +{c.insertions} -{c.deletions}"
        )
    return "\n".join(lines)


def _format_file_structure(files: list[str], max_files: int = 60) -> str:
    sample = files[:max_files]
    result = "\n".join(sample)
    if len(files) > max_files:
        result += f"\n... and {len(files) - max_files} more files"
    return result


def run(repo: GitRepo, config: Config, claude: ClaudeClient) -> dict:
    """Fetch commits, call Claude, return structured evolution analysis."""
    commits = repo.get_commits(max_count=config.max_commits)

    if not commits:
        return {
            "total_analyzed": 0,
            "phases": [],
            "commits": [],
            "architecture_drift": {"detected": False, "description": "No commits found"},
            "overall_summary": "Empty repository.",
        }

    commit_list_text = _format_commit_list(commits)
    file_structure_text = _format_file_structure(repo.get_tracked_files())

    prompt = COMMIT_EVOLUTION_USER.format(
        repo_name=repo.get_name(),
        language=repo.detect_language(),
        remote_url=repo.get_remote_url() or "local",
        total_commits=len(commits),
        commit_list=commit_list_text,
        file_structure=file_structure_text,
    )

    raw = claude.ask_json(COMMIT_EVOLUTION_SYSTEM, prompt, max_tokens=6000)

    # Enrich claude output with our local commit data
    commit_map: dict[str, CommitInfo] = {c.hash: c for c in commits}
    enriched_commits: list[dict] = []

    for ca in raw.get("commits", []):
        full_hash = ca.get("hash", "")
        local = commit_map.get(full_hash)
        entry = {
            "hash": full_hash,
            "short_hash": full_hash[:7],
            "message": local.message if local else "",
            "author": local.author if local else "",
            "date": local.date if local else "",
            "stats": {
                "files_changed": local.files_changed if local else 0,
                "insertions": local.insertions if local else 0,
                "deletions": local.deletions if local else 0,
            },
            "ai_analysis": {
                "type": ca.get("type", "chore"),
                "necessary": ca.get("necessary", True),
                "reasoning": ca.get("reasoning", ""),
                "issues": ca.get("issues", []),
                "quality_score": ca.get("quality_score", 0.0),
                "phase": ca.get("phase", "unknown"),
            },
        }
        enriched_commits.append(entry)

    return {
        "total_analyzed": len(commits),
        "phases": raw.get("phases", []),
        "commits": enriched_commits,
        "architecture_drift": raw.get("architecture_drift", {}),
        "overall_summary": raw.get("overall_summary", ""),
    }