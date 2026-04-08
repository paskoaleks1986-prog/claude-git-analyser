"""Release Agent — Block 3, final step. Score 0-100 with full context."""
from __future__ import annotations

from ai.client import ClaudeClient
from ai.prompts import RELEASE_READINESS_SYSTEM, RELEASE_READINESS_USER
from config import Config
from git.repo import GitRepo
from setup.stack_detector import StackInfo


def _blocks_overview(block_data: dict) -> str:
    blocks = block_data.get("blocks", [])
    if not blocks:
        return "No blocks analysed"
    lines = []
    for b in blocks:
        lines.append(
            f"  Block {b.get('id')}: {b.get('name')} "
            f"score={b.get('quality_score', 0)}/10 "
            f"impact={b.get('architecture_impact', '?')}"
        )
        if b.get("issues"):
            lines.append(f"    Issues: {'; '.join(b['issues'][:2])}")
    return "\n".join(lines)


def _quality_results(quality_data: dict) -> str:
    linter = quality_data.get("linter", {})
    tests = quality_data.get("tests", {})
    comments = quality_data.get("inline_comments", {})
    comment_count = sum(len(comments.get(k, [])) for k in ("todos", "fixmes", "personal"))
    linter_str = (
        "linter: PASSED" if linter.get("passed")
        else f"linter: {linter.get('errors', 0)} errors, {linter.get('warnings', 0)} warnings"
        if linter.get("available") else f"linter: {linter.get('skipped_reason', 'unavailable')}"
    )
    test_str = (
        f"tests: {tests.get('passed', 0)} passed / {tests.get('failed', 0)} failed"
        + (f", coverage {tests['coverage_percent']}%" if tests.get("coverage_percent") else "")
        if tests.get("framework") not in ("none", None)
        else f"tests: {tests.get('skipped_reason', 'none found')}"
    )
    return f"{linter_str}\n{test_str}\ninline comments: {comment_count}"


def _env_summary(release_files: dict) -> str:
    readme = release_files.get("readme", {})
    lines = [
        f"README: {'YES score=' + str(readme.get('completeness_score', 0)) + '/100' if readme.get('exists') else 'MISSING'}",
        f"requirements/deps: {'YES' if release_files.get('requirements', {}).get('exists') else 'NO'}",
        f".env.example: {'YES' if release_files.get('env_example', {}).get('exists') else 'NO'}",
        f"Docker: {'YES' if release_files.get('docker', {}).get('dockerfile') else 'NO'}",
        f"CI/CD: {'YES' if release_files.get('ci_cd', {}).get('exists') else 'NO'}",
        f"CHANGELOG: {'YES' if release_files.get('changelog', {}).get('exists') else 'NO'}",
    ]
    return "\n".join(lines)


def _branch_summary(branch_data: dict) -> str:
    s = branch_data.get("summary", {})
    stale = [b["name"] for b in branch_data.get("branches", []) if b["status"] == "stale"]
    lines = [f"Total: {s.get('total', 0)}, Active: {s.get('active', 0)}, Stale: {s.get('stale', 0)}"]
    if stale:
        lines.append(f"Stale: {', '.join(stale[:4])}")
    return "\n".join(lines)


def run(
    repo: GitRepo, config: Config, claude: ClaudeClient,
    block_data: dict, arch_data: dict, quality_data: dict, dynamic_data: dict,
    release_files: dict, branch_data: dict, stack: StackInfo,
) -> dict:
    stack_label = ", ".join(stack.languages[:2] + stack.frameworks[:2]) or "unknown"
    verdict = arch_data.get("architecture_verdict", {})
    drift = arch_data.get("drift", {})

    prompt = RELEASE_READINESS_USER.format(
        repo_name=repo.get_name(),
        stack=stack_label,
        framework=", ".join(stack.frameworks) or "not detected",
        services=", ".join(stack.services) or "none",
        arch_health=verdict.get("overall_health", "unknown"),
        arch_drift=f"YES — {drift.get('description', '')}" if drift.get("detected") else "No",
        dynamics_summary=dynamic_data.get("dynamics_summary", "N/A"),
        blocks_overview=_blocks_overview(block_data),
        quality_results=_quality_results(quality_data),
        env_summary=_env_summary(release_files),
        branch_summary=_branch_summary(branch_data),
    )

    raw = claude.ask_json(RELEASE_READINESS_SYSTEM, prompt, max_tokens=2500)

    return {
        "score": raw.get("score", 0),
        "status": raw.get("status", "not_ready"),
        "blockers": raw.get("blockers", []),
        "warnings": raw.get("warnings", []),
        "recommendations": raw.get("recommendations", []),
        "summary": raw.get("summary", ""),
    }