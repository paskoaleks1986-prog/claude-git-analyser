"""Tool checker — verifies tools, asks user before installing. Never silently skips."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from setup.stack_detector import StackInfo


@dataclass
class ToolStatus:
    name: str
    available: bool
    version: str = ""
    install_cmd: str = ""
    user_declined: bool = False


@dataclass
class ToolCheckResult:
    tools: list[ToolStatus] = field(default_factory=list)

    def is_available(self, name: str) -> bool:
        return any(t.name == name and t.available for t in self.tools)

    def available_linters(self) -> list[str]:
        lint_names = {"ruff", "eslint", "hadolint"}
        return [t.name for t in self.tools if t.available and t.name in lint_names]

    def available_test_runners(self) -> list[str]:
        test_names = {"pytest", "jest", "vitest"}
        return [t.name for t in self.tools if t.available and t.name in test_names]

    def declined(self) -> list[str]:
        return [t.name for t in self.tools if t.user_declined]


INSTALL_COMMANDS: dict[str, str] = {
    "ruff":       "pip install ruff",
    "pytest":     "pip install pytest",
    "pytest-cov": "pip install pytest-cov",
    "eslint":     "npm install -g eslint",
    "jest":       "npm install -g jest",
    "vitest":     "npm install -g vitest",
    "hadolint":   "brew install hadolint  # or: apt install hadolint",
}


def _check_tool(name: str) -> ToolStatus:
    path = shutil.which(name)
    if path:
        try:
            result = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=5)
            version = (result.stdout + result.stderr).strip().split("\n")[0]
        except (subprocess.TimeoutExpired, OSError):
            version = "unknown"
        return ToolStatus(name=name, available=True, version=version,
                          install_cmd=INSTALL_COMMANDS.get(name, ""))
    return ToolStatus(name=name, available=False, install_cmd=INSTALL_COMMANDS.get(name, ""))


def _ask_install(tool: ToolStatus, interactive: bool) -> bool:
    if not interactive:
        return False
    print(f"\n  ⚠  [{tool.name}] not found")
    if tool.install_cmd:
        print(f"     Install with: {tool.install_cmd}")
    answer = input("     Install now? [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def _try_install(tool: ToolStatus) -> bool:
    cmd = tool.install_cmd
    if not cmd or "#" in cmd:
        print(f"     Cannot auto-install {tool.name}. Install manually.")
        return False
    print(f"     Installing {tool.name}...", flush=True)
    try:
        parts = cmd.split()
        if parts[0] == "pip":
            parts = [sys.executable, "-m", "pip"] + parts[1:]
        result = subprocess.run(parts, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print(f"     ✓ {tool.name} installed")
            return True
        else:
            print(f"     ✗ Failed: {result.stderr.strip()[:200]}")
            return False
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"     ✗ Error: {e}")
        return False


def run(stack: StackInfo, interactive: bool = True) -> ToolCheckResult:
    result = ToolCheckResult()
    all_tools = list(dict.fromkeys(stack.lint_tools + stack.test_tools))
    if not all_tools:
        return result
    if interactive:
        print("\n  Checking analysis tools...")
    for tool_name in all_tools:
        status = _check_tool(tool_name)
        if status.available:
            if interactive:
                print(f"  ✓ {tool_name} ({status.version})")
        else:
            if interactive:
                want_install = _ask_install(status, interactive)
                if want_install:
                    success = _try_install(status)
                    if success:
                        status = _check_tool(tool_name)
                    else:
                        status.user_declined = False
                else:
                    status.user_declined = True
                    print(f"     Skipping {tool_name} — analysis will be partial")
        result.tools.append(status)
    return result