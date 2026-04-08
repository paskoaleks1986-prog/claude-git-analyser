"""Orchestrator — three-block pipeline coordinator."""
from __future__ import annotations

from rich.console import Console
from rich.markup import escape

from agents import architecture_agent, block_analyzer, branch_agent, dynamic_analyzer
from agents import quality_agent, release_agent
from ai.client import make_client
from config import Config
from git import grouper
from git.branch_matcher import enrich_block_data_with_files, match_blocks
from git.repo import GitRepo
from report import terminal, yaml_export
from setup import stack_detector, tool_checker

console = Console()

# ── Branch hierarchy detection ─────────────────────────────────────────────────

_HIERARCHY: list[list[str]] = [
    ["prod", "preprod", "dev"],
    ["prod", "staging", "dev"],
    ["main", "preprod", "dev"],
    ["main", "staging", "dev"],
    ["master", "preprod", "dev"],
    ["master", "staging", "dev"],
    ["main", "dev"],
    ["master", "dev"],
    ["prod", "dev"],
]


def _detect_hierarchy(available: list[str]) -> list[str]:
    """Return ordered branch list [parent, ...children] from available branches."""
    available_set = set(available)
    for chain in _HIERARCHY:
        matched = [b for b in chain if b in available_set]
        if len(matched) >= 2:
            return matched
    # fallback: main/master alone
    for name in ("main", "master", "prod"):
        if name in available_set:
            return [name]
    return [available[0]] if available else []


def _attach_quality_flags_to_blocks(block_data: dict, quality_data: dict) -> dict:
    """
    Attach global quality flags to each block so terminal can render per-block flags.
    Global flags are the same for all blocks (we don't have per-block AST yet),
    but delta flags (coupling_delta, complexity_delta etc.) are block-specific.
    """
    global_flags = quality_data.get("flags", {})
    delta = quality_data.get("delta", {})

    blocks = block_data.get("blocks", [])
    for i, block in enumerate(blocks):
        block_flags = dict(global_flags)

        # overlay delta flags for the last block only (most recent change)
        if i == len(blocks) - 1:
            for dk, dv in delta.items():
                if isinstance(dv, dict) and "flag" in dv:
                    block_flags[dk] = dv["flag"]

        block["quality_flags"] = block_flags

    return block_data


# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline
# ══════════════════════════════════════════════════════════════════════════════

def run(config: Config) -> dict:
    config.validate()

    repo   = GitRepo(config.repo_path)
    claude = make_client(model=config.model, claude_path=config.claude_path, timeout=config.claude_timeout)
    progress = terminal.make_progress()

    # ── BLOCK 1: Data Collection ──────────────────────────────────────────────
    console.print()
    console.print("[bold cyan]━━━  BLOCK 1: Data Collection  ━━━[/]")

    with progress:
        t = progress.add_task("[cyan]Detecting stack...", total=None)
        stack = stack_detector.detect(repo.path)
        progress.remove_task(t)

    terminal.print_header(
        repo_name=repo.get_name(),
        language=stack.primary_language,
        frameworks=stack.frameworks,
        services=stack.services,
        remote=repo.get_remote_url(),
    )

    tools = tool_checker.run(stack, interactive=not config.non_interactive)

    with progress:
        t = progress.add_task("[cyan]Analysing branches...", total=None)
        branch_data = branch_agent.run(repo, config)
        progress.remove_task(t)

    terminal.print_branches(branch_data)

    with progress:
        t = progress.add_task("[cyan]Scanning release files...", total=None)
        release_files = repo.check_release_files()
        progress.remove_task(t)

    # detect branch hierarchy
    available_branches = [b["name"] for b in branch_data.get("branches", [])]
    hierarchy = _detect_hierarchy(available_branches)
    hierarchy_display = "  →  ".join(escape(b) for b in hierarchy) if hierarchy else "none detected"
    console.print(f"  Branch hierarchy: [cyan]{hierarchy_display}[/]")
    console.print()

    analysis: dict = {
        "repository": {
            "name": repo.get_name(),
            "path": str(repo.path),
            "primary_language": stack.primary_language,
            "languages": stack.languages,
            "frameworks": stack.frameworks,
            "services": stack.services,
            "package_managers": stack.package_managers,
            "ci_provider": stack.ci_provider,
            "total_commits": repo.get_total_commits(),
            "last_activity": repo.get_last_activity(),
            "remote_url": repo.get_remote_url(),
        },
        "branches": branch_data,
        "branch_hierarchy": hierarchy,
    }

    # ── BLOCK 2: Semantic Engine — per branch ─────────────────────────────────
    console.print()
    console.print("[bold cyan]━━━  BLOCK 2: Semantic Engine  ━━━[/]")

    with progress:
        t = progress.add_task("[cyan]Running code quality checks...", total=None)
        quality_data = quality_agent.run(repo, config, stack, tools)
        progress.remove_task(t)

    branch_block_data: dict[str, dict] = {}    # branch_name → block_data
    branch_match_results: dict[str, dict] = {} # branch_name → match result
    parent_block_data: dict | None = None
    parent_branch_name: str = hierarchy[0] if hierarchy else ""

    for idx, branch_name in enumerate(hierarchy):
        with progress:
            t = progress.add_task(
                f"[cyan]Loading commits: {escape(branch_name)}...", total=None,
            )
            commits = repo.get_commits_for_branch(branch_name, max_count=config.max_commits)
            draft_groups = grouper.group(commits)
            progress.remove_task(t)

        with progress:
            t = progress.add_task(
                f"[cyan]Analysing {len(draft_groups)} blocks "
                f"({escape(branch_name)}) (Claude)...",
                total=None,
            )
            block_data = block_analyzer.run(repo, config, claude, draft_groups, stack)
            progress.remove_task(t)

        # enrich blocks with touched files for matching
        block_data = enrich_block_data_with_files(block_data, repo, stack)

        # attach quality flags to each block
        block_data = _attach_quality_flags_to_blocks(block_data, quality_data)

        # match against parent branch (all branches except the first)
        match_ref: dict | None = None
        if idx > 0 and parent_block_data is not None:
            with progress:
                t = progress.add_task(
                    f"[cyan]Matching {escape(branch_name)} → "
                    f"{escape(parent_branch_name)}...",
                    total=None,
                )
                match_result = match_blocks(
                    parent_blocks=parent_block_data.get("blocks", []),
                    child_blocks=block_data.get("blocks", []),
                    child_branch=branch_name,
                    parent_branch=parent_branch_name,
                )
                progress.remove_task(t)
                match_ref = match_result.as_ref_dict()
                branch_match_results[branch_name] = {
                    "matched": match_result.matched_count,
                    "total": match_result.total_count,
                    "match_rate": round(match_result.match_rate, 2),
                    "details": [
                        {
                            "block_id": m.child_block_id,
                            "block_name": m.child_block_name,
                            "matched": m.matched,
                            "similarity": m.similarity,
                            "reason": m.reason,
                        }
                        for m in match_result.block_matches
                    ],
                }

        terminal.print_blocks(block_data, branch_name=branch_name, match_ref=match_ref)

        branch_block_data[branch_name] = block_data

        # first branch becomes parent for subsequent branches
        if idx == 0:
            parent_block_data = block_data
            parent_branch_name = branch_name

    # use parent (main/prod) block data for architecture + dynamics
    primary_block_data = (
        branch_block_data.get(hierarchy[0], {"blocks": []}) if hierarchy else {"blocks": []}
    )

    with progress:
        t = progress.add_task("[cyan]Building architecture timeline (Claude)...", total=None)
        arch_data = architecture_agent.run(repo, claude, primary_block_data["blocks"], stack)
        progress.remove_task(t)

    terminal.print_architecture(arch_data)

    analysis["commit_evolution"] = primary_block_data
    analysis["branch_blocks"]    = branch_block_data
    analysis["branch_matches"]   = branch_match_results
    analysis["architecture"]     = arch_data

    # ── BLOCK 3: Synthesis ────────────────────────────────────────────────────
    console.print()
    console.print("[bold cyan]━━━  BLOCK 3: Synthesis  ━━━[/]")

    terminal.print_quality(quality_data)

    with progress:
        t = progress.add_task("[cyan]Analysing dynamics (Claude)...", total=None)
        dynamic_data = dynamic_analyzer.run(
            repo, claude, primary_block_data["blocks"], arch_data, quality_data, stack,
        )
        progress.remove_task(t)

    terminal.print_dynamics(dynamic_data)

    with progress:
        t = progress.add_task("[cyan]Assessing release readiness (Claude)...", total=None)
        readiness_data = release_agent.run(
            repo=repo, config=config, claude=claude,
            block_data=primary_block_data, arch_data=arch_data,
            quality_data=quality_data, dynamic_data=dynamic_data,
            release_files=release_files, branch_data=branch_data, stack=stack,
        )
        progress.remove_task(t)

    terminal.print_release_readiness(readiness_data)

    analysis["code_quality"]      = quality_data
    analysis["dynamics"]          = dynamic_data
    analysis["release_readiness"] = readiness_data
    analysis["environment"]       = release_files

    yaml_path = yaml_export.export(analysis, config.output_file)
    terminal.print_footer(yaml_path)

    return analysis
