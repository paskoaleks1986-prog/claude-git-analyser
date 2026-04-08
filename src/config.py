"""Central configuration for claude-check-repo."""
from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class Config:
    repo_path: str = "."
    output_format: str = "yaml"
    output_file: str = "repo_analysis.yaml"
    model: str = "claude-opus-4-5"
    max_commits: int = 100
    stale_branch_days: int = 30
    deep_analysis: bool = False
    fix_mode: bool = False
    non_interactive: bool = False   # skip tool install prompts
    claude_path: str = "claude"     # path to claude CLI binary

    def validate(self) -> None:
        """Verify that the claude CLI is available in PATH."""
        if not shutil.which(self.claude_path):
            raise ValueError(
                f"claude CLI not found at '{self.claude_path}'.\n"
                "Install Claude Code: https://claude.ai/code\n"
                "Then log in via OAuth — no API key required."
            )