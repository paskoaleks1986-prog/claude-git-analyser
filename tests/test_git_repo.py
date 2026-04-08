"""Full test suite v1.1."""
from __future__ import annotations
import json, subprocess, tempfile, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(scope="module")
def git_repo_path(tmp_path_factory):
    d = tmp_path_factory.mktemp("repo")
    run = lambda *cmd: subprocess.run(list(cmd), cwd=d, capture_output=True, text=True)
    run("git","init"); run("git","config","user.email","t@t.com"); run("git","config","user.name","T")
    (d/"Dockerfile").write_text("FROM python:3.11\n")
    (d/".env.example").write_text("DEBUG=false\nDB_URL=\n")
    run("git","add","."); run("git","commit","-m","chore: docker and env")
    (d/"main.py").write_text("# TODO: error handling\ndef main(): pass\n")
    (d/"config.py").write_text("# FIXME: validate\nDEBUG=False\n")
    (d/"README.md").write_text("# Repo\n## Install\npip install .\n## Usage\npython main.py\n## Examples\nsee tests\n")
    run("git","add","."); run("git","commit","-m","feat: app structure")
    (d/"client.ts").write_text("// HACK: temp\nexport const API='http://localhost';\n")
    run("git","add","."); run("git","commit","-m","feat: ts client")
    tests=d/"tests"; tests.mkdir()
    (tests/"test_main.py").write_text("def test_ok(): assert True\n")
    run("git","add","."); run("git","commit","-m","test: basic tests")
    run("git","checkout","-b","old-feature")
    (d/"old.py").write_text("# wip\n"); run("git","add","."); run("git","commit","-m","wip")
    run("git","checkout","master")
    return d


@pytest.fixture(scope="module")
def repo(git_repo_path):
    from git.repo import GitRepo
    return GitRepo(str(git_repo_path))


@pytest.fixture(scope="module")
def config():
    from config import Config
    return Config()


class TestGitRepo:
    def test_init_invalid(self, tmp_path):
        from git.repo import GitRepo
        with pytest.raises(ValueError): GitRepo(str(tmp_path))
    def test_name(self, repo): assert repo.get_name()
    def test_total_commits(self, repo): assert repo.get_total_commits() == 4
    def test_commits_oldest_first(self, repo):
        c = repo.get_commits()[0]
        assert "docker" in c.message.lower() or "chore" in c.message.lower()
    def test_commit_fields(self, repo):
        c = repo.get_commits()[0]
        assert len(c.hash)==40 and c.short_hash and c.message and c.author and c.date
    def test_language_python(self, repo): assert repo.detect_language()=="Python"
    def test_block_diff(self, repo):
        commits=repo.get_commits()
        diff=repo.get_block_diff(commits[0].hash, commits[-1].hash, [".py",".ts"])
        assert isinstance(diff,str) and len(diff)>0
    def test_file_tree_at(self, repo):
        commits=repo.get_commits()
        assert "main.py" in repo.get_file_tree_at(commits[-1].hash)
    def test_file_tree_start_no_main(self, repo):
        assert "main.py" not in repo.get_file_tree_at(repo.get_commits()[0].hash)
    def test_inline_todo(self, repo):
        assert len(repo.scan_inline_comments({".py":"#",".ts":"//"})[  "todos"])>=1
    def test_inline_fixme(self, repo):
        assert len(repo.scan_inline_comments({".py":"#",".ts":"//"})[  "fixmes"])>=1
    def test_inline_hack_ts(self, repo):
        assert len(repo.scan_inline_comments({".py":"#",".ts":"//"})[  "personal"])>=1
    def test_release_readme(self, repo):
        rf=repo.check_release_files()
        assert rf["readme"]["exists"] and rf["readme"]["completeness_score"]>0
    def test_release_docker(self, repo):
        assert repo.check_release_files()["docker"]["dockerfile"]
    def test_release_env_example(self, repo):
        assert repo.check_release_files()["env_example"]["exists"]
    def test_release_no_ci(self, repo):
        assert not repo.check_release_files()["ci_cd"]["exists"]


def _mc(hash_, msg, date="2026-01-01 10:00:00 +0000"):
    from git.repo import CommitInfo
    return CommitInfo(hash=hash_,short_hash=hash_[:7],message=msg,
                      author="dev",date=date,files_changed=2,insertions=5,deletions=1)


class TestGrouper:
    def test_empty(self):
        from git.grouper import group
        assert group([]) == []
    def test_single(self):
        from git.grouper import group
        assert len(group([_mc("a01","init")])) == 1
    def test_all_kept(self):
        from git.grouper import group
        assert sum(len(g.commits) for g in group([_mc(f"a0{i}","msg") for i in range(6)])) == 6
    def test_time_gap_splits(self):
        from git.grouper import group
        commits=[_mc("a01","feat","2026-01-01 10:00:00 +0000"),
                 _mc("a02","feat","2026-01-01 10:30:00 +0000"),
                 _mc("a03","docs","2026-01-02 06:00:00 +0000")]
        assert len(group(commits)) >= 2
    def test_infra_hint(self):
        from git.grouper import group
        g=group([_mc("a01","add dockerfile"),_mc("a02","add docker-compose")])
        assert any(x.hint in ("infrastructure","mixed") for x in g)
    def test_format(self):
        from git.grouper import group, format_for_claude
        assert "DRAFT GROUP" in format_for_claude(group([_mc("a01","init")]))


def _mk(files):
    d=Path(tempfile.mkdtemp())
    for name,content in files.items():
        p=d/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content)
    return d


class TestStackDetector:
    def test_python(self):
        from setup.stack_detector import detect
        assert detect(_mk({"a.py":"x=1\n","b.py":"y=2\n"})).primary_language=="Python"
    def test_fastapi(self):
        from setup.stack_detector import detect
        assert "FastAPI" in detect(_mk({"app.py":"from fastapi import FastAPI\n"})).frameworks
    def test_nuxt(self):
        from setup.stack_detector import detect
        s=detect(_mk({"nuxt.config.ts":"export default {}\n",
                       "package.json":json.dumps({"dependencies":{"nuxt":"3.0"}})}))
        assert "Nuxt" in s.frameworks
    def test_postgres(self):
        from setup.stack_detector import detect
        s=detect(_mk({"a.py":"x=1\n","docker-compose.yml":"services:\n  db:\n    image: postgres:15\n"}))
        assert "Postgres" in s.services
    def test_redis(self):
        from setup.stack_detector import detect
        s=detect(_mk({"a.py":"x=1\n","docker-compose.yml":"services:\n  c:\n    image: redis:7\n"}))
        assert "Redis" in s.services
    def test_rabbitmq(self):
        from setup.stack_detector import detect
        s=detect(_mk({"a.py":"x=1\n","docker-compose.yml":"services:\n  mq:\n    image: rabbitmq:3\n"}))
        assert "RabbitMQ" in s.services
    def test_ruff_lint(self):
        from setup.stack_detector import detect
        assert "ruff" in detect(_mk({"a.py":"x=1\n"})).lint_tools
    def test_pytest_test(self):
        from setup.stack_detector import detect
        assert "pytest" in detect(_mk({"a.py":"x=1\n"})).test_tools
    def test_github_ci(self):
        from setup.stack_detector import detect
        s=detect(_mk({"a.py":"x=1\n",".github/workflows/ci.yml":"on: push\n"}))
        assert s.ci_provider=="github_actions"
    def test_empty(self):
        from setup.stack_detector import detect
        assert detect(Path(tempfile.mkdtemp())).primary_language=="unknown"


class TestToolChecker:
    def test_non_interactive(self):
        from setup.tool_checker import run, ToolCheckResult
        from setup.stack_detector import StackInfo
        r=run(StackInfo(lint_tools=["ruff"],test_tools=["pytest"]),interactive=False)
        assert isinstance(r,ToolCheckResult)
    def test_empty_stack(self):
        from setup.tool_checker import run
        from setup.stack_detector import StackInfo
        assert run(StackInfo(),interactive=False).tools==[]
    def test_available_linters(self):
        from setup.tool_checker import ToolCheckResult, ToolStatus
        r=ToolCheckResult(tools=[ToolStatus("ruff",True),ToolStatus("eslint",False)])
        assert r.available_linters()==["ruff"]
    def test_declined(self):
        from setup.tool_checker import ToolCheckResult, ToolStatus
        r=ToolCheckResult(tools=[ToolStatus("ruff",False,user_declined=True),ToolStatus("pytest",True)])
        assert "ruff" in r.declined() and "pytest" not in r.declined()


class TestBranchAgent:
    def test_structure(self, repo, config):
        from agents import branch_agent
        d=branch_agent.run(repo,config)
        assert "main_branch" in d and "summary" in d and "branches" in d
    def test_main_status(self, repo, config):
        from agents import branch_agent
        d=branch_agent.run(repo,config)
        m=next(b for b in d["branches"] if b["name"]==d["main_branch"])
        assert m["status"]=="main" and m["recommendation"]=="keep"


class TestYamlExport:
    def test_creates_file(self, tmp_path):
        from report import yaml_export
        assert Path(yaml_export.export({"x":1},str(tmp_path/"o.yaml"))).exists()
    def test_meta(self, tmp_path):
        import yaml
        from report import yaml_export
        d=yaml.safe_load(Path(yaml_export.export({"k":"v"},str(tmp_path/"o.yaml"))).read_text())
        assert d["meta"]["tool"]=="claude-check-repo"
    def test_unicode(self, tmp_path):
        from report import yaml_export
        p=yaml_export.export({"m":"Анализ"},str(tmp_path/"u.yaml"))
        assert "Анализ" in Path(p).read_text(encoding="utf-8")