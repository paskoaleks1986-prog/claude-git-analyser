"""Git repository data extractor — pure subprocess, no gitpython."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CommitInfo:
    hash: str
    short_hash: str
    message: str
    author: str
    date: str
    files_changed: int
    insertions: int
    deletions: int


@dataclass
class BranchInfo:
    name: str
    last_commit_hash: str
    last_commit_date: str
    author: str
    is_current: bool


class GitRepo:
    def __init__(self, path: str) -> None:
        self.path = Path(path).resolve()
        self._validate()

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, cwd=self.path, capture_output=True, text=True, timeout=60,
        )

    def _validate(self) -> None:
        result = self._run(["git", "rev-parse", "--git-dir"])
        if result.returncode != 0:
            raise ValueError(f"Not a git repository: {self.path}")

    def get_name(self) -> str:
        return self.path.name

    def get_remote_url(self) -> Optional[str]:
        result = self._run(["git", "remote", "get-url", "origin"])
        return result.stdout.strip() if result.returncode == 0 else None

    def get_current_branch(self) -> str:
        result = self._run(["git", "branch", "--show-current"])
        return result.stdout.strip() or "HEAD"

    def get_main_branch(self) -> str:
        for name in ["main", "master", "develop", "dev"]:
            r = self._run(["git", "branch", "--list", name])
            if r.stdout.strip():
                return name
        return self.get_current_branch()

    def get_total_commits(self) -> int:
        result = self._run(["git", "rev-list", "--count", "HEAD"])
        try:
            return int(result.stdout.strip())
        except ValueError:
            return 0

    def get_last_activity(self) -> str:
        result = self._run(["git", "log", "-1", "--format=%ai"])
        return result.stdout.strip()

    def get_commits(self, max_count: int = 100) -> list[CommitInfo]:
        result = self._run([
            "git", "log", f"--max-count={max_count}", "--reverse",
            "--format=%H|||%h|||%s|||%an|||%ai",
        ])
        commits: list[CommitInfo] = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|||")
            if len(parts) < 5:
                continue
            hash_, short_hash, message, author, date = parts[:5]
            stat_result = self._run(["git", "show", "--shortstat", "--format=", hash_])
            files, ins, dels = self._parse_shortstat(stat_result.stdout)
            commits.append(CommitInfo(
                hash=hash_.strip(), short_hash=short_hash.strip(),
                message=message.strip(), author=author.strip(), date=date.strip(),
                files_changed=files, insertions=ins, deletions=dels,
            ))
        return commits

    def _parse_shortstat(self, text: str) -> tuple[int, int, int]:
        files = ins = dels = 0
        if m := re.search(r"(\d+) file", text):
            files = int(m.group(1))
        if m := re.search(r"(\d+) insertion", text):
            ins = int(m.group(1))
        if m := re.search(r"(\d+) deletion", text):
            dels = int(m.group(1))
        return files, ins, dels

    def get_branches(self) -> list[BranchInfo]:
        result = self._run([
            "git", "branch", "-a",
            "--format=%(refname:short)|||%(objectname:short)|||%(committerdate:iso)|||%(authoremail)|||%(HEAD)",
        ])
        branches: list[BranchInfo] = []
        seen: set[str] = set()
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|||")
            if len(parts) < 5:
                continue
            name, hash_, date, author, head = parts[:5]
            name = name.strip()
            if "HEAD" in name and "->" in name:
                continue
            clean = re.sub(r"^(remotes/origin/|origin/)", "", name)
            if clean in seen:
                continue
            seen.add(clean)
            branches.append(BranchInfo(
                name=clean, last_commit_hash=hash_.strip(),
                last_commit_date=date.strip(), author=author.strip(),
                is_current=head.strip() == "*",
            ))
        return branches

    def count_unmerged_commits(self, branch: str, base: str) -> int:
        result = self._run(["git", "rev-list", "--count", f"{base}..{branch}"])
        try:
            return int(result.stdout.strip())
        except ValueError:
            return 0

    def get_tracked_files(self) -> list[str]:
        result = self._run(["git", "ls-files"])
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

    def detect_language(self) -> str:
        ext_count: dict[str, int] = {}
        for f in self.get_tracked_files():
            ext = Path(f).suffix.lower()
            if ext:
                ext_count[ext] = ext_count.get(ext, 0) + 1
        lang_map = {
            ".py": "Python", ".ts": "TypeScript", ".js": "JavaScript",
            ".rs": "Rust", ".go": "Go", ".java": "Java", ".rb": "Ruby",
            ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C",
        }
        if not ext_count:
            return "Unknown"
        top_ext = max(ext_count, key=ext_count.__getitem__)
        return lang_map.get(top_ext, top_ext.lstrip(".").capitalize())

    def detect_framework(self) -> Optional[str]:
        files = set(self.get_tracked_files())
        indicators = {
            "Django": {"manage.py", "django"},
            "FastAPI": {"fastapi"},
            "Flask": {"flask"},
            "Next.js": {"next.config.js", "next.config.ts"},
            "NestJS": {"nest-cli.json"},
        }
        for framework, markers in indicators.items():
            for marker in markers:
                if any(marker in f for f in files):
                    return framework
        return None

    # ── Block diffs ──────────────────────────────────────────────────

    def get_block_diff(
        self,
        from_hash: str,
        to_hash: str,
        source_extensions: list[str] | None = None,
        max_chars: int = 3000,
    ) -> str:
        stat_result = self._run(["git", "diff", "--stat", f"{from_hash}^", to_hash])
        stat = stat_result.stdout.strip()
        ext_patterns = source_extensions or [".py", ".ts", ".js", ".vue"]
        path_specs = [f"*{ext}" for ext in ext_patterns]
        diff_result = self._run(
            ["git", "diff", "--unified=2", f"{from_hash}^", to_hash, "--"] + path_specs
        )
        raw_diff = diff_result.stdout
        if len(raw_diff) > max_chars:
            raw_diff = raw_diff[:max_chars] + f"\n... [truncated, {len(raw_diff)} chars total]"
        return f"=== File changes ===\n{stat}\n\n=== Code diff ===\n{raw_diff}".strip()

    def get_file_tree_at(self, commit_hash: str) -> str:
        result = self._run(["git", "ls-tree", "-r", "--name-only", commit_hash])
        files = [f for f in result.stdout.strip().split("\n") if f]
        preview = "\n".join(files[:40])
        if len(files) > 40:
            preview += f"\n... and {len(files) - 40} more"
        return preview

    # ── Inline comments ──────────────────────────────────────────────

    def scan_inline_comments(
        self,
        comment_prefix_map: dict[str, str] | None = None,
    ) -> dict:
        todos: list[dict] = []
        fixmes: list[dict] = []
        personal: list[dict] = []
        if comment_prefix_map is None:
            comment_prefix_map = {
                ".py": "#", ".js": "//", ".ts": "//", ".tsx": "//",
                ".vue": "//", ".go": "//", ".rs": "//", ".java": "//",
            }
        for filepath in self.get_tracked_files()[:80]:
            ext = Path(filepath).suffix.lower()
            prefix = comment_prefix_map.get(ext)
            if not prefix:
                continue
            try:
                full_path = self.path / filepath
                for i, raw_line in enumerate(full_path.read_text(errors="ignore").splitlines(), 1):
                    line = raw_line.strip()
                    if not line.startswith(prefix):
                        continue
                    text = line[len(prefix):].strip()
                    upper = text.upper()
                    entry = {"file": filepath, "line": i, "text": text}
                    if upper.startswith("TODO"):
                        todos.append(entry)
                    elif upper.startswith("FIXME"):
                        fixmes.append(entry)
                    elif any(upper.startswith(k) for k in ("HACK", "XXX", "TEMP", "WTF", "NOTE:")):
                        personal.append(entry)
            except (OSError, UnicodeDecodeError):
                pass
        return {"todos": todos[:20], "fixmes": fixmes[:20], "personal": personal[:20]}

    # ── Release files ────────────────────────────────────────────────

    def check_release_files(self) -> dict:
        def exists(*globs: str) -> tuple[bool, Optional[str]]:
            for g in globs:
                matches = list(self.path.glob(g))
                if matches:
                    return True, str(matches[0].relative_to(self.path))
            return False, None

        readme_exists, readme_path = exists("README*", "readme*")
        readme_data: dict = {"exists": readme_exists, "path": readme_path}
        if readme_exists and readme_path:
            try:
                content = (self.path / readme_path).read_text(errors="ignore").lower()
                readme_data["has_install"] = any(w in content for w in ["install", "pip ", "npm "])
                readme_data["has_usage"] = any(w in content for w in ["usage", "example", "quickstart"])
                readme_data["has_examples"] = "example" in content or "```" in content
                score = sum([
                    30 * readme_data["has_install"],
                    30 * readme_data["has_usage"],
                    20 * readme_data["has_examples"],
                    20,
                ])
                readme_data["completeness_score"] = score
            except OSError:
                readme_data["completeness_score"] = 20
        else:
            readme_data.update({"has_install": False, "has_usage": False,
                                 "has_examples": False, "completeness_score": 0})

        req_exists, req_path = exists("requirements*.txt", "pyproject.toml", "package.json")
        env_exists, env_path = exists(".env.example", ".env.sample", ".env.template")
        docker_exists, _ = exists("Dockerfile", "dockerfile")
        compose_exists, _ = exists("docker-compose*.yml", "docker-compose*.yaml")
        ci_github, _ = exists(".github/workflows/*.yml", ".github/workflows/*.yaml")
        ci_gitlab, _ = exists(".gitlab-ci.yml", ".gitlab-ci.yaml")
        changelog_exists, _ = exists("CHANGELOG*", "HISTORY*", "changelog*")

        return {
            "readme": readme_data,
            "requirements": {"exists": req_exists, "path": req_path},
            "env_example": {"exists": env_exists, "path": env_path},
            "docker": {"dockerfile": docker_exists, "compose": compose_exists},
            "ci_cd": {"github_actions": ci_github, "gitlab_ci": ci_gitlab,
                      "exists": ci_github or ci_gitlab},
            "changelog": {"exists": changelog_exists},
        }
