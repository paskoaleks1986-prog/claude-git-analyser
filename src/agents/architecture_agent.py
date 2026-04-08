"""Architecture Agent — Block 2, Step 2. Timeline + drift detection."""
from __future__ import annotations

from ai.client import ClaudeClient
from ai.prompts import ARCHITECTURE_AGENT_SYSTEM, ARCHITECTURE_AGENT_USER
from git.repo import GitRepo
from setup.stack_detector import StackInfo


def _blocks_summary(blocks: list[dict]) -> str:
    lines: list[str] = []
    for b in blocks:
        lines.append(
            f"Block {b.get('id')}: {b.get('name')} | "
            f"type={b.get('type')} | score={b.get('quality_score', 0)}/10 | "
            f"impact={b.get('architecture_impact', 'unknown')}"
        )
        lines.append(f"  Summary: {b.get('summary', '')}")
        if issues := b.get("issues", []):
            lines.append(f"  Issues: {'; '.join(issues[:2])}")
    return "\n".join(lines)


def run(repo: GitRepo, claude: ClaudeClient, blocks: list[dict], stack: StackInfo) -> dict:
    if not blocks:
        return {
            "timeline": [],
            "drift": {"detected": False, "description": "No blocks to analyse"},
            "architecture_verdict": {"overall_health": "unknown",
                                     "key_finding": "Repository appears empty"},
        }

    all_commit_hashes = [h for b in blocks for h in b.get("commits", [])]
    file_tree_start = repo.get_file_tree_at(all_commit_hashes[0]) if all_commit_hashes else ""
    file_tree_end = repo.get_file_tree_at("HEAD")

    prompt = ARCHITECTURE_AGENT_USER.format(
        repo_name=repo.get_name(),
        stack=", ".join(stack.languages[:2] + stack.frameworks[:2]) or "unknown",
        services=", ".join(stack.services) or "none",
        blocks_summary=_blocks_summary(blocks),
        file_tree_start=file_tree_start,
        file_tree_end=file_tree_end,
    )

    raw = claude.ask_json(ARCHITECTURE_AGENT_SYSTEM, prompt, max_tokens=3000)

    return {
        "timeline": raw.get("timeline", []),
        "drift": raw.get("drift", {"detected": False}),
        "architecture_verdict": raw.get("architecture_verdict", {}),
    }