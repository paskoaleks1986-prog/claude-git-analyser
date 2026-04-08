"""CLI entry point — claude-check-repo."""
from __future__ import annotations
import sys
import click
from rich.console import Console
from config import Config
import orchestrator

console = Console()


@click.command()
@click.argument("repo_path", default=".", required=False)
@click.option("--output", "-o", default="repo_analysis.yaml", show_default=True)
@click.option("--model", "-m", default="claude-opus-4-5", show_default=True)
@click.option("--max-commits", default=100, show_default=True)
@click.option("--stale-days", default=30, show_default=True)
@click.option("--claude-path", default="claude", show_default=True,
              help="Path to claude CLI binary.")
@click.option("--deep", is_flag=True, default=False, help="Deep analysis mode")
@click.option("--no-interactive", is_flag=True, default=False,
              help="Skip tool install prompts (CI mode)")
@click.option("--timeout", default=300, show_default=True,
              help="Timeout in seconds for each Claude API call.")
def main(repo_path, output, model, max_commits, stale_days, claude_path, deep, no_interactive, timeout):
    """claude-check-repo — AI-powered repository evolution analyzer.

    Authenticates via Claude subscription (OAuth) — no API key needed.

    \b
    Examples:
      claude-check-repo
      claude-check-repo ./my-project
      claude-check-repo ./my-project --output report.yaml
      claude-check-repo ./my-project --no-interactive
      claude-check-repo ./my-project --claude-path /usr/local/bin/claude
    """
    config = Config(
        repo_path=repo_path,
        output_file=output,
        model=model,
        max_commits=max_commits,
        stale_branch_days=stale_days,
        claude_path=claude_path,
        deep_analysis=deep,
        non_interactive=no_interactive,
        claude_timeout=timeout,
    )
    try:
        orchestrator.run(config)
    except ValueError as e:
        console.print(f"\n[bold red]Error:[/] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/] {e}")
        if deep:
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()