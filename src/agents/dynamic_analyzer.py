"""Dynamic Analyzer — Block 3, Step 1. Quality curve + impact analysis."""
from __future__ import annotations

from ai.client import ClaudeClient
from ai.prompts import DYNAMIC_ANALYZER_SYSTEM, DYNAMIC_ANALYZER_USER
from git.repo import GitRepo
from setup.stack_detector import StackInfo


def _quality_curve_text(blocks: list[dict]) -> str:
    lines: list[str] = []
    for b in blocks:
        score = b.get("quality_score", 0)
        bar = "█" * int(score) + "░" * (10 - int(score))
        lines.append(f"  Block {b.get('id'):>2} [{bar}] {score:.1f}  {b.get('name', '')}")
    return "\n".join(lines)


def _arch_timeline_text(arch_data: dict) -> str:
    lines: list[str] = []
    for t in arch_data.get("timeline", []):
        lines.append(
            f"  After block {t.get('after_block')}: {t.get('architecture_state', '')} "
            f"[{t.get('health', 'unknown')}]"
        )
    drift = arch_data.get("drift", {})
    if drift.get("detected"):
        lines.append(f"\n  DRIFT detected at block {drift.get('drift_started_at_block')}")
        lines.append(f"  {drift.get('description', '')}")
    verdict = arch_data.get("architecture_verdict", {})
    lines.append(f"\n  Overall health: {verdict.get('overall_health', 'unknown')}")
    lines.append(f"  Key finding: {verdict.get('key_finding', '')}")
    return "\n".join(lines)


def _quality_results_text(quality_data: dict) -> str:
    linter = quality_data.get("linter", {})
    tests = quality_data.get("tests", {})
    comments = quality_data.get("inline_comments", {})
    linter_str = (
        "ruff: PASSED" if linter.get("passed")
        else f"ruff: {linter.get('errors', 0)} errors, {linter.get('warnings', 0)} warnings"
        if linter.get("available") else "linter: not available"
    )
    cov = tests.get("coverage_percent")
    test_str = (
        f"pytest: {tests.get('passed', 0)} passed / {tests.get('failed', 0)} failed"
        + (f", coverage {cov}%" if cov else "")
        if tests.get("framework") != "none" else "tests: none found"
    )
    comment_count = sum(len(comments.get(k, [])) for k in ("todos", "fixmes", "personal"))
    return f"  {linter_str}\n  {test_str}\n  inline comments: {comment_count} (TODO/FIXME/HACK)"


def run(repo: GitRepo, claude: ClaudeClient, blocks: list[dict],
        arch_data: dict, quality_data: dict, stack: StackInfo) -> dict:
    if not blocks:
        return {"quality_curve": [], "inflection_points": [], "harmful_blocks": [],
                "best_blocks": [], "dynamics_summary": "No data available."}

    stack_label = ", ".join(stack.languages[:2] + stack.frameworks[:2]) or "unknown"

    prompt = DYNAMIC_ANALYZER_USER.format(
        repo_name=repo.get_name(),
        stack=stack_label,
        quality_curve=_quality_curve_text(blocks),
        arch_timeline=_arch_timeline_text(arch_data),
        block_summaries="\n".join(
            f"  Block {b.get('id')}: {b.get('name')} — {b.get('verdict', '')}"
            for b in blocks
        ),
        quality_results=_quality_results_text(quality_data),
    )

    raw = claude.ask_json(DYNAMIC_ANALYZER_SYSTEM, prompt, max_tokens=2500)

    return {
        "quality_curve": raw.get("quality_curve", []),
        "inflection_points": raw.get("inflection_points", []),
        "harmful_blocks": raw.get("harmful_blocks", []),
        "best_blocks": raw.get("best_blocks", []),
        "dynamics_summary": raw.get("dynamics_summary", ""),
    }