"""Terminal reporter — Rich output for all three pipeline blocks."""
from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table

console = Console()

# ── Metric flag → icon ────────────────────────────────────────────────────────

_FLAG_ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢"}

_METRIC_SHORT = {
    "cyclomatic_complexity": "complexity",
    "coupling":              "coupling",
    "circular_imports":      "circular",
    "god_objects":           "god_obj",
    "fat_models":            "fat_model",
    "dead_code":             "dead_code",
    "mutable_default_args":  "mut_default",
    "side_effects_in_init":  "init_sideeff",
    "swallowed_exceptions":  "swallowed_exc",
    "global_mutation":       "global_mut",
    "multiple_return_types": "multi_return",
    "long_functions":        "long_fn",
    "deep_nesting":          "deep_nest",
    "n_plus_one":            "n+1",
    "repeated_db_calls":     "repeat_db",
    "missing_pagination":    "no_pagination",
    "heavy_loop_recalc":     "heavy_loop",
    "hardcoded_credentials": "hardcoded_creds",
    "sql_injection":         "sql_inject",
    "coupling_delta":        "Δcoupling",
    "complexity_delta":      "Δcomplexity",
    "circular_import_new":   "Δcircular",
    "god_object_new":        "Δgod_obj",
}


def _flags_line(flags: dict) -> str:
    """Build a compact flags line: 🔴 n+1  🟡 coupling  (only non-green)."""
    parts: list[str] = []
    for metric, flag in flags.items():
        if flag in ("red", "yellow"):
            icon = _FLAG_ICON[flag]
            label = _METRIC_SHORT.get(metric, metric)  # hardcoded dict — safe
            parts.append(f"{icon} {label}")
    return "  ".join(parts) if parts else "🟢 clean"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 1 — Data Collection
# ══════════════════════════════════════════════════════════════════════════════

def print_header(
    repo_name: str,
    language: str,
    frameworks: list[str],
    services: list[str],
    remote: str | None,
) -> None:
    fw  = escape(", ".join(frameworks) if frameworks else "—")
    svc = escape(", ".join(services) if services else "—")
    console.print()
    console.print(Panel(
        f"[bold cyan]claude-check-repo[/]\n"
        f"[white]Repository:[/] [bold]{escape(repo_name)}[/]\n"
        f"[white]Language:[/]   [yellow]{escape(language)}[/]   "
        f"[white]Frameworks:[/] [yellow]{fw}[/]\n"
        f"[white]Services:[/]  [yellow]{svc}[/]\n"
        f"[white]Remote:[/]    [dim]{escape(remote or 'local')}[/]",
        border_style="cyan",
        expand=False,
    ))
    console.print()


def print_branches(branch_data: dict) -> None:
    console.print(Rule("[bold blue]Branches[/]", style="blue"))
    s = branch_data.get("summary", {})
    console.print(
        f"  Total: [bold]{s.get('total', 0)}[/]  "
        f"Active: [green]{s.get('active', 0)}[/]  "
        f"Stale: [yellow]{s.get('stale', 0)}[/]  "
        f"Long-running: [red]{s.get('long_running', 0)}[/]"
    )
    table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 2))
    table.add_column("Branch")
    table.add_column("Status")
    table.add_column("Age")
    table.add_column("Unmerged")
    table.add_column("Action")

    icons = {
        "main": "[green]●[/]", "active": "[green]●[/]",
        "stale": "[yellow]●[/]", "long_running": "[red]●[/]",
    }
    actions = {
        "keep": "[green]keep[/]", "delete": "[red]delete[/]",
        "merge_or_delete": "[yellow]merge/delete[/]", "review": "[yellow]review[/]",
    }
    for b in branch_data.get("branches", []):
        status = b["status"]
        rec    = b["recommendation"]
        table.add_row(
            f"{icons.get(status, '●')} {escape(b['name'])}",
            escape(status),
            f"{b['age_days']}d",
            str(b["unmerged_commits"]),
            actions.get(rec, escape(rec)),
        )
    console.print(table)
    console.print()


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 2 — Commit Evolution
# ══════════════════════════════════════════════════════════════════════════════

def print_blocks(block_data: dict, branch_name: str = "", match_ref: dict | None = None) -> None:
    """
    New layout: each block is a header line with hash range + score,
    metric flags on the next line.

    match_ref: dict of ref_block_id → ref_block (from parent branch) for ✅/❌
    """
    branch_label = f"BRANCH: {escape(branch_name)}" if branch_name else "BRANCH: main"
    console.print()
    console.print(Rule(f"[bold cyan]{branch_label}[/]", style="cyan"))

    blocks = block_data.get("blocks", [])
    total  = block_data.get("total_commits", 0)
    console.print(f"  {total} commits → [bold]{len(blocks)} blocks[/]")
    if note := block_data.get("grouping_notes"):
        console.print(f"  [dim]{escape(note)}[/]")
    console.print()

    for b in blocks:
        bid     = b.get("id", "?")
        name    = escape(b.get("name", "").upper())
        score   = b.get("quality_score", 0)
        commits = b.get("commits", [])
        flags   = b.get("quality_flags", {})
        summary = b.get("summary", "")
        issues  = b.get("issues", [])

        # hash range — hex chars only, safe without escape
        first_h    = commits[0][:7] if commits else "?"
        last_h     = commits[-1][:7] if commits else "?"
        hash_range = f"{first_h}..{last_h}" if first_h != last_h else first_h

        sc = "green" if score >= 7 else "yellow" if score >= 4 else "red"

        match_icon = ""
        if match_ref is not None:
            matched    = match_ref.get(bid, None)
            match_icon = "  [green]✅ matched[/]" if matched else "  [red]❌ not matched[/]"

        # ── header line ──────────────────────────────────────────────────────
        console.print(
            f"[bold]Block {bid}[/] [cyan]{name}[/]  "
            f"[dim]{hash_range}[/]  "
            f"score: [{sc}]{score:.1f}[/]"
            f"{match_icon}"
        )

        # ── flags line ───────────────────────────────────────────────────────
        if flags:
            console.print(f"  {_flags_line(flags)}")

        # ── summary + issues ─────────────────────────────────────────────────
        if summary:
            console.print(f"  [dim]{escape(summary)}[/]")
        for issue in issues[:2]:
            console.print(f"  [yellow]⚠[/] [dim]{escape(issue)}[/]")

        console.print()


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 2 — Architecture
# ══════════════════════════════════════════════════════════════════════════════

def print_architecture(arch_data: dict) -> None:
    console.print(Rule("[bold blue]Architecture Timeline[/]", style="blue"))
    verdict = arch_data.get("architecture_verdict", {})
    health  = verdict.get("overall_health", "unknown")
    hc = {"healthy": "green", "degraded": "yellow", "broken": "red"}.get(health, "white")
    console.print(f"  Overall health: [{hc}]{escape(health.upper())}[/]")
    if finding := verdict.get("key_finding"):
        console.print(f"  [dim]{escape(finding)}[/]")
    drift = arch_data.get("drift", {})
    if drift.get("detected"):
        console.print(
            f"\n  [bold red]⚠ Architecture Drift[/] "
            f"(from block {drift.get('drift_started_at_block')})\n"
            f"  [dim]{escape(drift.get('description', ''))}[/]"
        )
    console.print()


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 3 — Quality (global summary, not per-block)
# ══════════════════════════════════════════════════════════════════════════════

def print_quality(quality_data: dict) -> None:
    """Global quality summary — shown once after all branches."""
    console.print(Rule("[bold blue]Code Quality — Global[/]", style="blue"))

    flags   = quality_data.get("flags", {})
    metrics = quality_data.get("metrics", {})
    langs   = quality_data.get("languages_analysed", [])

    if langs:
        console.print(f"  Languages analysed: [dim]{escape(', '.join(langs))}[/]")

    non_green = {k: v for k, v in flags.items() if v in ("red", "yellow")}
    if not non_green:
        console.print("  [green]✓ All metrics clean[/]")
    else:
        for metric, flag in non_green.items():
            icon  = _FLAG_ICON[flag]
            label = _METRIC_SHORT.get(metric, metric)  # hardcoded dict — safe
            raw   = metrics.get(metric)
            count = ""
            if isinstance(raw, list):
                count = f" ({len(raw)})"
            elif isinstance(raw, dict) and "violations" in raw:
                count = f" ({len(raw['violations'])})"
            elif isinstance(raw, dict) and "pairs" in raw:
                count = f" ({len(raw['pairs'])})"
            console.print(f"  {icon} [bold]{label}[/]{count}")

    comments = quality_data.get("inline_comments", {})
    todos    = len(comments.get("todos", []))
    fixmes   = len(comments.get("fixmes", []))
    personal = len(comments.get("personal", []))
    if todos or fixmes or personal:
        console.print(
            f"  [yellow]⚠ Comments:[/] "
            f"{todos} TODO  {fixmes} FIXME  {personal} HACK/XXX"
        )
    console.print()


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 3 — Dynamics
# ══════════════════════════════════════════════════════════════════════════════

def print_dynamics(dynamic_data: dict) -> None:
    console.print(Rule("[bold blue]Quality Dynamics[/]", style="blue"))
    curve = dynamic_data.get("quality_curve", [])
    if curve:
        console.print("  [bold]Quality curve:[/]")
        for point in curve:
            score = point.get("score", 0)
            sc    = "green" if score >= 7 else "yellow" if score >= 4 else "red"
            bar   = "█" * int(score) + "░" * (10 - int(score))
            trend = point.get("trend", "")
            trend_icon = {
                "degradation": " [red]↓[/]",
                "improvement": " [green]↑[/]",
                "recovery":    " [green]↑[/]",
            }.get(trend, "")
            console.print(
                f"    Block {point.get('block_id'):>2} [{sc}]{bar}[/] "
                f"[{sc}]{score:.1f}[/]  {escape(point.get('block_name', ''))}{trend_icon}"
            )
        console.print()
    if harmful := dynamic_data.get("harmful_blocks", []):
        console.print("  [bold red]Harmful blocks:[/]")
        for h in harmful:
            console.print(
                f"    [red]✗ Block {h.get('block_id')} — {escape(h.get('name', ''))}[/]"
            )
            console.print(f"    [dim]  {escape(h.get('reason', ''))}[/]")
            console.print(f"    [dim]  → {escape(h.get('suggestion', ''))}[/]")
        console.print()
    if summary := dynamic_data.get("dynamics_summary"):
        console.print(f"  [dim]{escape(summary)}[/]")
    console.print()


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 3 — Release Readiness
# ══════════════════════════════════════════════════════════════════════════════

def print_release_readiness(release_data: dict) -> None:
    console.print(Rule("[bold blue]Release Readiness[/]", style="blue"))
    score  = release_data.get("score", 0)
    status = release_data.get("status", "not_ready")
    sc     = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    status_display = {
        "ready":        "[bold green]READY ✓[/]",
        "almost_ready": "[bold yellow]ALMOST READY ⚠[/]",
        "needs_work":   "[bold red]NEEDS WORK ✗[/]",
        "not_ready":    "[bold red]NOT READY ✗[/]",
    }.get(status, escape(status.upper()))
    console.print(Panel(
        f"Score: [{sc}]{score}/100[/]   {status_display}\n\n"
        f"[dim]{escape(release_data.get('summary', ''))}[/]",
        border_style=sc,
        expand=False,
    ))
    if blockers := release_data.get("blockers", []):
        console.print("\n  [bold red]Blockers:[/]")
        for b in blockers:
            console.print(f"    [red]✗[/] {escape(b)}")
    if warnings := release_data.get("warnings", []):
        console.print("\n  [bold yellow]Warnings:[/]")
        for w in warnings:
            console.print(f"    [yellow]⚠[/] {escape(w)}")
    if recs := release_data.get("recommendations", []):
        console.print("\n  [bold]Recommendations:[/]")
        pc = {"high": "red", "medium": "yellow", "low": "dim"}
        for r in recs:
            pri    = r.get("priority", "medium")
            effort = r.get("effort", "")
            effort_str = f" [dim]({escape(effort)})[/]" if effort else ""
            console.print(
                f"    [{pc.get(pri, 'white')}]{escape(pri.upper())}[/] "
                f"[cyan]{escape(r.get('category', ''))}[/] — "
                f"{escape(r.get('action', ''))}{effort_str}"
            )
    console.print()


def print_footer(yaml_path: str) -> None:
    console.print(Rule(style="dim"))
    console.print(f"  [dim]Report saved:[/] [bold]{escape(yaml_path)}[/]")
    console.print()
