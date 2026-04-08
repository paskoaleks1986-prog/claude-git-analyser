"""Terminal reporter — Rich output for all three pipeline blocks."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table

console = Console()


def make_progress() -> Progress:
    return Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                    console=console, transient=True)


def print_header(repo_name: str, language: str, frameworks: list[str],
                 services: list[str], remote: str | None) -> None:
    fw = ", ".join(frameworks) if frameworks else "—"
    svc = ", ".join(services) if services else "—"
    console.print()
    console.print(Panel(
        f"[bold cyan]claude-check-repo[/]\n"
        f"[white]Repository:[/] [bold]{repo_name}[/]\n"
        f"[white]Language:[/]   [yellow]{language}[/]   [white]Frameworks:[/] [yellow]{fw}[/]\n"
        f"[white]Services:[/]  [yellow]{svc}[/]\n"
        f"[white]Remote:[/]    [dim]{remote or 'local'}[/]",
        border_style="cyan", expand=False,
    ))
    console.print()


def print_branches(branch_data: dict) -> None:
    console.print(Rule("[bold blue]Branches[/]", style="blue"))
    s = branch_data.get("summary", {})
    console.print(
        f"  Total: [bold]{s.get('total', 0)}[/]  Active: [green]{s.get('active', 0)}[/]  "
        f"Stale: [yellow]{s.get('stale', 0)}[/]  Long-running: [red]{s.get('long_running', 0)}[/]"
    )
    table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 2))
    table.add_column("Branch"); table.add_column("Status")
    table.add_column("Age"); table.add_column("Unmerged"); table.add_column("Action")
    icons = {"main": "[green]●[/]", "active": "[green]●[/]",
              "stale": "[yellow]●[/]", "long_running": "[red]●[/]"}
    actions = {"keep": "[green]keep[/]", "delete": "[red]delete[/]",
               "merge_or_delete": "[yellow]merge/delete[/]", "review": "[yellow]review[/]"}
    for b in branch_data.get("branches", []):
        table.add_row(
            f"{icons.get(b['status'], '●')} {b['name']}", b["status"],
            f"{b['age_days']}d", str(b["unmerged_commits"]),
            actions.get(b["recommendation"], b["recommendation"]),
        )
    console.print(table)
    console.print()


def print_blocks(block_data: dict) -> None:
    console.print(Rule("[bold blue]Commit Evolution — Semantic Blocks[/]", style="blue"))
    blocks = block_data.get("blocks", [])
    total = block_data.get("total_commits", 0)
    console.print(f"  {total} commits → [bold]{len(blocks)} semantic blocks[/]")
    if note := block_data.get("grouping_notes"):
        console.print(f"  [dim]{note}[/]")
    console.print()
    for b in blocks:
        score = b.get("quality_score", 0)
        sc = "green" if score >= 7 else "yellow" if score >= 4 else "red"
        impact = b.get("architecture_impact", "low")
        ic = {"low": "dim", "medium": "yellow", "high": "red", "breaking": "bold red"}.get(impact, "white")
        console.print(
            f"  [bold]Block {b.get('id')}[/] [cyan]{b.get('name', '').upper()}[/]"
            f"  [{sc}]{score:.1f}/10[/]  impact=[{ic}]{impact}[/]"
            f"  ({len(b.get('commits', []))} commits)"
        )
        console.print(f"    [dim]{b.get('summary', '')}[/]")
        for issue in b.get("issues", [])[:2]:
            console.print(f"    [yellow]⚠[/] [dim]{issue}[/]")
        if verdict := b.get("verdict"):
            console.print(f"    [italic dim]→ {verdict}[/]")
        console.print()


def print_architecture(arch_data: dict) -> None:
    console.print(Rule("[bold blue]Architecture Timeline[/]", style="blue"))
    verdict = arch_data.get("architecture_verdict", {})
    health = verdict.get("overall_health", "unknown")
    hc = {"healthy": "green", "degraded": "yellow", "broken": "red"}.get(health, "white")
    console.print(f"  Overall health: [{hc}]{health.upper()}[/]")
    if finding := verdict.get("key_finding"):
        console.print(f"  [dim]{finding}[/]")
    drift = arch_data.get("drift", {})
    if drift.get("detected"):
        console.print(
            f"\n  [bold red]⚠ Architecture Drift[/] (from block {drift.get('drift_started_at_block')})\n"
            f"  [dim]{drift.get('description', '')}[/]"
        )
    console.print()


def print_quality(quality_data: dict) -> None:
    console.print(Rule("[bold blue]Code Quality[/]", style="blue"))
    linter = quality_data.get("linter", {})
    if not linter.get("available"):
        console.print(f"  [dim]Linter: {linter.get('skipped_reason', 'not available')}[/]")
    elif linter.get("passed"):
        console.print(f"  [green]✓ {linter.get('tool', 'linter')}: PASSED[/]")
    else:
        console.print(
            f"  [red]✗ {linter.get('tool', 'linter')}: "
            f"{linter.get('errors', 0)} errors, {linter.get('warnings', 0)} warnings[/]"
        )
        for i in linter.get("top_issues", [])[:4]:
            console.print(f"    [dim]{i.get('code')} {i.get('message')} — {i.get('file')}[/]")
    tests = quality_data.get("tests", {})
    if tests.get("framework") == "none":
        console.print("  [red]✗ Tests: none found[/]")
    elif "skipped_reason" in tests:
        console.print(f"  [dim]Tests: {tests['skipped_reason']}[/]")
    else:
        cov = tests.get("coverage_percent")
        cov_str = f"  coverage: [bold]{cov}%[/]" if cov is not None else ""
        icon = "[green]✓[/]" if tests.get("failed", 0) == 0 and tests.get("total_tests", 0) > 0 else "[red]✗[/]"
        console.print(
            f"  {icon} Tests ({tests.get('framework')}): "
            f"[green]{tests.get('passed', 0)} passed[/] / "
            f"[red]{tests.get('failed', 0)} failed[/] ({tests.get('total_tests', 0)} total){cov_str}"
        )
    comments = quality_data.get("inline_comments", {})
    todos = len(comments.get("todos", []))
    fixmes = len(comments.get("fixmes", []))
    personal = len(comments.get("personal", []))
    if todos or fixmes or personal:
        console.print(f"  [yellow]⚠ Comments: {todos} TODO  {fixmes} FIXME  {personal} HACK/XXX[/]")
    console.print()


def print_dynamics(dynamic_data: dict) -> None:
    console.print(Rule("[bold blue]Quality Dynamics[/]", style="blue"))
    curve = dynamic_data.get("quality_curve", [])
    if curve:
        console.print("  [bold]Quality curve:[/]")
        for point in curve:
            score = point.get("score", 0)
            sc = "green" if score >= 7 else "yellow" if score >= 4 else "red"
            bar = "█" * int(score) + "░" * (10 - int(score))
            trend = point.get("trend", "")
            trend_icon = {"degradation": " [red]↓[/]", "improvement": " [green]↑[/]",
                          "recovery": " [green]↑[/]"}.get(trend, "")
            console.print(
                f"    Block {point.get('block_id'):>2} [{sc}]{bar}[/] "
                f"[{sc}]{score:.1f}[/]  {point.get('block_name', '')}{trend_icon}"
            )
        console.print()
    if harmful := dynamic_data.get("harmful_blocks", []):
        console.print("  [bold red]Harmful blocks:[/]")
        for h in harmful:
            console.print(f"    [red]✗ Block {h.get('block_id')} — {h.get('name')}[/]")
            console.print(f"    [dim]  {h.get('reason', '')}[/]")
            console.print(f"    [dim]  → {h.get('suggestion', '')}[/]")
        console.print()
    if summary := dynamic_data.get("dynamics_summary"):
        console.print(f"  [dim]{summary}[/]")
    console.print()


def print_release_readiness(release_data: dict) -> None:
    console.print(Rule("[bold blue]Release Readiness[/]", style="blue"))
    score = release_data.get("score", 0)
    status = release_data.get("status", "not_ready")
    sc = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    status_display = {
        "ready": "[bold green]READY ✓[/]", "almost_ready": "[bold yellow]ALMOST READY ⚠[/]",
        "needs_work": "[bold red]NEEDS WORK ✗[/]", "not_ready": "[bold red]NOT READY ✗[/]",
    }.get(status, status.upper())
    console.print(Panel(
        f"Score: [{sc}]{score}/100[/]   {status_display}\n\n[dim]{release_data.get('summary', '')}[/]",
        border_style=sc, expand=False,
    ))
    if blockers := release_data.get("blockers", []):
        console.print("\n  [bold red]Blockers:[/]")
        for b in blockers:
            console.print(f"    [red]✗[/] {b}")
    if warnings := release_data.get("warnings", []):
        console.print("\n  [bold yellow]Warnings:[/]")
        for w in warnings:
            console.print(f"    [yellow]⚠[/] {w}")
    if recs := release_data.get("recommendations", []):
        console.print("\n  [bold]Recommendations:[/]")
        pc = {"high": "red", "medium": "yellow", "low": "dim"}
        for r in recs:
            pri = r.get("priority", "medium")
            effort = r.get("effort", "")
            effort_str = f" [dim]({effort})[/]" if effort else ""
            console.print(
                f"    [{pc.get(pri, 'white')}][{pri.upper()}][/] "
                f"[cyan]{r.get('category', '')}[/] — {r.get('action', '')}{effort_str}"
            )
    console.print()


def print_footer(yaml_path: str) -> None:
    console.print(Rule(style="dim"))
    console.print(f"  [dim]Report saved:[/] [bold]{yaml_path}[/]")
    console.print()