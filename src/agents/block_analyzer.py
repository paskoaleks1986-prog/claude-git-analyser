"""Block Analyzer — Block 2, Step 1. Replaces commit_agent."""
from __future__ import annotations

from ai.client import ClaudeClient
from ai.prompts import BLOCK_ANALYZER_SYSTEM, BLOCK_ANALYZER_USER
from config import Config
from git.grouper import DraftGroup, format_for_claude
from git.repo import GitRepo
from setup.stack_detector import StackInfo


def _build_block_diffs(repo: GitRepo, groups: list[DraftGroup], stack: StackInfo) -> str:
    max_chars_per_block = max(1500, 12000 // max(len(groups), 1))
    parts: list[str] = []
    for g in groups:
        if not g.commits:
            continue
        try:
            diff = repo.get_block_diff(
                from_hash=g.first_hash,
                to_hash=g.last_hash,
                source_extensions=stack.source_extensions or [".py", ".ts", ".js"],
                max_chars=max_chars_per_block,
            )
            parts.append(f"\n=== DIFF: Group {g.id} ({g.hint}) ===\n{diff}")
        except Exception as exc:
            parts.append(f"\n=== DIFF: Group {g.id} — unavailable ({exc}) ===")
    return "\n".join(parts)


def _stack_label(stack: StackInfo) -> str:
    parts = stack.languages[:2] + stack.frameworks[:2]
    if stack.services:
        parts.append(f"+ {', '.join(stack.services[:3])}")
    return ", ".join(parts) or "unknown"


def run(repo: GitRepo, config: Config, claude: ClaudeClient,
        groups: list[DraftGroup], stack: StackInfo) -> dict:
    if not groups:
        return {"blocks": [], "grouping_notes": "No commits found"}

    all_commits = [c for g in groups for c in g.commits]
    first_hash = all_commits[0].hash if all_commits else "HEAD"
    last_hash = all_commits[-1].hash if all_commits else "HEAD"

    prompt = BLOCK_ANALYZER_USER.format(
        repo_name=repo.get_name(),
        stack=_stack_label(stack),
        total_commits=len(all_commits),
        draft_groups=format_for_claude(groups),
        file_tree_start=repo.get_file_tree_at(first_hash),
        file_tree_now=repo.get_file_tree_at(last_hash),
        block_diffs=_build_block_diffs(repo, groups, stack),
    )

    raw = claude.ask_json(BLOCK_ANALYZER_SYSTEM, prompt, max_tokens=6000)

    return {
        "blocks": raw.get("blocks", []),
        "grouping_notes": raw.get("grouping_notes", ""),
        "total_blocks": len(raw.get("blocks", [])),
        "total_commits": len(all_commits),
    }