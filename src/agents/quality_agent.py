"""Quality Agent — Block 3, Step 2. Multi-stack linting and testing."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from config import Config
from git.repo import GitRepo
from setup.stack_detector import StackInfo
from setup.tool_checker import ToolCheckResult


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _run_ruff(repo_path: Path, tool_status: ToolCheckResult) -> dict:
    if not tool_status.is_available("ruff"):
        return {"tool": "ruff", "available": False,
                "skipped_reason": "ruff not installed (user declined or unavailable)"}
    result = _run(["ruff", "check", ".", "--output-format", "json"], cwd=repo_path)
    passed = result.returncode == 0
    try:
        issues: list[dict] = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        issues = []
    errors = [i for i in issues if i.get("code", "").startswith(("E", "F"))]
    warnings = [i for i in issues if not i.get("code", "").startswith(("E", "F"))]
    return {
        "tool": "ruff", "available": True, "passed": passed,
        "total_issues": len(issues), "errors": len(errors), "warnings": len(warnings),
        "top_issues": [{"code": i.get("code"), "message": i.get("message", ""),
                        "file": i.get("filename", "")} for i in issues[:10]],
    }


def _run_pytest(repo_path: Path, tool_status: ToolCheckResult) -> dict:
    test_files = [f for f in list(repo_path.rglob("test_*.py")) + list(repo_path.rglob("*_test.py"))
                  if "__pycache__" not in str(f)]
    if not test_files:
        return {"framework": "none", "files_found": 0, "total_tests": 0,
                "passed": 0, "failed": 0, "errors": 0, "coverage_percent": None,
                "skipped_reason": "No test files found"}
    if not tool_status.is_available("pytest"):
        return {"framework": "pytest", "files_found": len(test_files),
                "skipped_reason": "pytest not installed (user declined or unavailable)"}

    has_cov = tool_status.is_available("pytest-cov")
    cmd = ["python", "-m", "pytest", "--tb=no", "-q", "--no-header"]
    if has_cov:
        cmd += ["--cov=.", "--cov-report=json"]
    result = _run(cmd, cwd=repo_path, timeout=180)
    output = result.stdout + result.stderr

    passed = failed = errors_count = 0
    if m := re.search(r"(\d+) passed", output):
        passed = int(m.group(1))
    if m := re.search(r"(\d+) failed", output):
        failed = int(m.group(1))
    if m := re.search(r"(\d+) error", output):
        errors_count = int(m.group(1))

    coverage_percent: float | None = None
    coverage_json = repo_path / "coverage.json"
    if coverage_json.exists():
        try:
            cov_data = json.loads(coverage_json.read_text())
            coverage_percent = round(cov_data.get("totals", {}).get("percent_covered", 0), 1)
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "framework": "pytest", "files_found": len(set(test_files)),
        "total_tests": passed + failed + errors_count,
        "passed": passed, "failed": failed, "errors": errors_count,
        "coverage_percent": coverage_percent,
    }


def _run_eslint(repo_path: Path, tool_status: ToolCheckResult) -> dict:
    if not tool_status.is_available("eslint"):
        return {"tool": "eslint", "available": False,
                "skipped_reason": "eslint not installed (user declined or unavailable)"}
    result = _run(["eslint", ".", "--ext", ".js,.ts,.vue,.jsx,.tsx", "--format", "json"],
                  cwd=repo_path)
    passed = result.returncode == 0
    try:
        raw: list[dict] = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        raw = []
    errors = sum(f.get("errorCount", 0) for f in raw)
    warnings = sum(f.get("warningCount", 0) for f in raw)
    return {
        "tool": "eslint", "available": True, "passed": passed,
        "total_issues": errors + warnings, "errors": errors, "warnings": warnings,
        "top_issues": [
            {"file": r.get("filePath", "").replace(str(repo_path), "").lstrip("/"),
             "errors": r.get("errorCount", 0), "warnings": r.get("warningCount", 0)}
            for r in raw[:5] if r.get("errorCount", 0) + r.get("warningCount", 0) > 0
        ],
    }


def _run_js_tests(repo_path: Path, tool_status: ToolCheckResult) -> dict:
    for runner in ("jest", "vitest"):
        if tool_status.is_available(runner):
            flag = "--run" if runner == "vitest" else "--passWithNoTests"
            result = _run([runner, flag, "--reporter=json"], cwd=repo_path, timeout=120)
            try:
                data = json.loads(result.stdout or "{}")
                return {"framework": runner, "total_tests": data.get("numTotalTests", 0),
                        "passed": data.get("numPassedTests", 0),
                        "failed": data.get("numFailedTests", 0),
                        "errors": 0, "coverage_percent": None}
            except json.JSONDecodeError:
                pass
    test_files = (list(repo_path.rglob("*.test.ts")) + list(repo_path.rglob("*.test.js"))
                  + list(repo_path.rglob("*.spec.ts")) + list(repo_path.rglob("*.spec.js")))
    if test_files:
        return {"framework": "jest/vitest", "files_found": len(test_files),
                "skipped_reason": "No test runner available"}
    return {"framework": "none", "files_found": 0, "skipped_reason": "No test files found"}


def run(repo: GitRepo, config: Config, stack: StackInfo, tools: ToolCheckResult) -> dict:
    repo_path = repo.path
    results: dict = {}

    linters: list[dict] = []
    if "Python" in stack.languages:
        linters.append(_run_ruff(repo_path, tools))
    if any(l in stack.languages for l in ("JavaScript", "TypeScript", "Vue")):
        linters.append(_run_eslint(repo_path, tools))
    results["linters"] = linters
    results["linter"] = linters[0] if linters else {"available": False, "skipped_reason": "No linter"}

    if "Python" in stack.languages:
        results["tests"] = _run_pytest(repo_path, tools)
    elif any(l in stack.languages for l in ("JavaScript", "TypeScript", "Vue")):
        results["tests"] = _run_js_tests(repo_path, tools)
    else:
        results["tests"] = {"framework": "none", "skipped_reason": "Unsupported language"}

    results["inline_comments"] = repo.scan_inline_comments(stack.comment_prefix_map)
    return results