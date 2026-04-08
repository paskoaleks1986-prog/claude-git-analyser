"""Orchestrator — three-block pipeline coordinator."""
from __future__ import annotations

from rich.console import Console

from agents import architecture_agent, block_analyzer, branch_agent, dynamic_analyzer
from agents import quality_agent, release_agent
from ai.client import make_client
from config import Config
from git import grouper
from git.repo import GitRepo
from report import terminal, yaml_export
from setup import stack_detector, tool_checker

console = Console()


def run(config: Config) -> dict:
    config.validate()

    repo = GitRepo(config.repo_path)
    claude = make_client(model=config.model, claude_path=config.claude_path)
    progress = terminal.make_progress()

    # ── BLOCK 1: Data Collection ──────────────────────────────────────
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
        t = progress.add_task("[cyan]Loading commits...", total=None)
        commits = repo.get_commits(max_count=config.max_commits)
        draft_groups = grouper.group(commits)
        progress.remove_task(t)

    with progress:
        t = progress.add_task("[cyan]Analysing branches...", total=None)
        branch_data = branch_agent.run(repo, config)
        progress.remove_task(t)

    terminal.print_branches(branch_data)

    with progress:
        t = progress.add_task("[cyan]Scanning release files...", total=None)
        release_files = repo.check_release_files()
        progress.remove_task(t)

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
    }

    # ── BLOCK 2: Semantic Engine ──────────────────────────────────────
    console.print()
    console.print("[bold cyan]━━━  BLOCK 2: Semantic Engine  ━━━[/]")

    with progress:
        t = progress.add_task(
            f"[cyan]Analysing {len(draft_groups)} commit blocks (Claude)...", total=None)
        block_data = block_analyzer.run(repo, config, claude, draft_groups, stack)
        progress.remove_task(t)

    terminal.print_blocks(block_data)

    with progress:
        t = progress.add_task("[cyan]Building architecture timeline (Claude)...", total=None)
        arch_data = architecture_agent.run(repo, claude, block_data["blocks"], stack)
        progress.remove_task(t)

    terminal.print_architecture(arch_data)

    analysis["commit_evolution"] = block_data
    analysis["architecture"] = arch_data

    # ── BLOCK 3: Synthesis ────────────────────────────────────────────
    console.print()
    console.print("[bold cyan]━━━  BLOCK 3: Synthesis  ━━━[/]")

    with progress:
        t = progress.add_task("[cyan]Running code quality checks...", total=None)
        quality_data = quality_agent.run(repo, config, stack, tools)
        progress.remove_task(t)

    terminal.print_quality(quality_data)

    with progress:
        t = progress.add_task("[cyan]Analysing dynamics (Claude)...", total=None)
        dynamic_data = dynamic_analyzer.run(
            repo, claude, block_data["blocks"], arch_data, quality_data, stack)
        progress.remove_task(t)

    terminal.print_dynamics(dynamic_data)

    with progress:
        t = progress.add_task("[cyan]Assessing release readiness (Claude)...", total=None)
        readiness_data = release_agent.run(
            repo=repo, config=config, claude=claude,
            block_data=block_data, arch_data=arch_data,
            quality_data=quality_data, dynamic_data=dynamic_data,
            release_files=release_files, branch_data=branch_data, stack=stack,
        )
        progress.remove_task(t)

    terminal.print_release_readiness(readiness_data)

    analysis["code_quality"] = quality_data
    analysis["dynamics"] = dynamic_data
    analysis["release_readiness"] = readiness_data
    analysis["environment"] = release_files

    yaml_path = yaml_export.export(analysis, config.output_file)
    terminal.print_footer(yaml_path)

    return analysis