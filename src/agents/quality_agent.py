"""Quality Agent — static AST/regex analysis across all supported languages."""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Any

from config import Config
from git.repo import GitRepo
from setup.stack_detector import StackInfo
from setup.tool_checker import ToolCheckResult

# ── Skip patterns ─────────────────────────────────────────────────────────────

_SKIP_DIRS = {
    "__pycache__", ".venv", "venv", "node_modules", ".git",
    "migrations", "dist", "build", ".next", ".nuxt",
}

_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB — защита от OOM на больших файлах


def _source_files(repo_path: Path, extensions: list[str]) -> list[Path]:
    result: list[Path] = []
    for f in repo_path.rglob("*"):
        if not f.is_file():
            continue
        if f.is_symlink():  # не следуем симлинкам за пределы репо
            continue
        if any(skip in f.parts for skip in _SKIP_DIRS):
            continue
        if f.suffix.lower() in extensions:
            result.append(f)
    return result


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return ""
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


# ── FLAG helper ───────────────────────────────────────────────────────────────

def _flag(items: list, warn_threshold: int = 1, err_threshold: int = 3) -> str:
    n = len(items)
    if n == 0:
        return "green"
    if n < err_threshold:
        return "yellow"
    return "red"


def _flag_value(value: float, warn: float, err: float) -> str:
    if value >= err:
        return "red"
    if value >= warn:
        return "yellow"
    return "green"


# ══════════════════════════════════════════════════════════════════════════════
# PYTHON — full AST
# ══════════════════════════════════════════════════════════════════════════════

class _PythonVisitor(ast.NodeVisitor):
    """Single-pass AST visitor collecting all Python metrics per file."""

    def __init__(self, source: str, filepath: str) -> None:
        self.source = source
        self.filepath = filepath
        self.lines = source.splitlines()

        # results
        self.imports: list[str] = []
        self.god_objects: list[dict] = []
        self.fat_models: list[dict] = []
        self.mutable_defaults: list[dict] = []
        self.side_effects_init: list[dict] = []
        self.swallowed_exceptions: list[dict] = []
        self.global_mutations: list[dict] = []
        self.multiple_return_types: list[dict] = []
        self.long_functions: list[dict] = []
        self.deep_nesting: list[dict] = []
        self.n_plus_one: list[dict] = []
        self.repeated_db_calls: list[dict] = []
        self.missing_pagination: list[dict] = []
        self.heavy_loop_recalc: list[dict] = []
        self.defined_names: set[str] = set()
        self.called_names: set[str] = set()
        self.hardcoded_creds: list[dict] = []
        self.sql_injection: list[dict] = []

        # internal
        self._loop_depth = 0
        self._nesting_depth = 0

    # ── imports ──────────────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append(node.module.split(".")[0])
        self.generic_visit(node)

    # ── classes ──────────────────────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
        if len(methods) > 20:
            self.god_objects.append({
                "class": node.name, "file": self.filepath,
                "methods": len(methods), "line": node.lineno,
            })

        # fat model: inherits from Model/Base
        base_names = {
            (b.id if isinstance(b, ast.Name) else
             b.attr if isinstance(b, ast.Attribute) else "")
            for b in node.bases
        }
        model_bases = {"Model", "Base", "AbstractModel", "TimeStampedModel"}
        if base_names & model_bases:
            skip = {"__str__", "__repr__", "__init__", "save", "clean",
                    "delete", "__unicode__", "get_absolute_url"}
            biz = [m for m in methods if m.name not in skip]
            if len(biz) > 3:
                self.fat_models.append({
                    "class": node.name, "file": self.filepath,
                    "business_methods": len(biz), "line": node.lineno,
                })

        self.generic_visit(node)

    # ── functions ─────────────────────────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defined_names.add(node.name)

        # mutable default args
        for default in node.args.defaults + node.args.kw_defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.mutable_defaults.append({
                    "file": self.filepath, "function": node.name, "line": node.lineno,
                })
                break

        # side effects in __init__
        if node.name == "__init__":
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    call_str = ast.unparse(child) if hasattr(ast, "unparse") else ""
                    if any(kw in call_str for kw in
                           ("open(", "request", "subprocess", ".objects.", ".filter(", ".get(")):
                        self.side_effects_init.append({
                            "file": self.filepath, "class": "<class>", "line": child.lineno,
                        })
                        break

        # long function
        length = node.end_lineno - node.lineno if node.end_lineno else 0
        if length > 50:
            self.long_functions.append({
                "file": self.filepath, "function": node.name, "lines": length,
            })

        # multiple return types
        returns: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                t = type(child.value).__name__
                returns.append(t)
        types = set(returns)
        if len(types) > 1 and "Constant" in types and len(types) > 1:
            self.multiple_return_types.append({
                "file": self.filepath, "function": node.name,
            })

        self._analyse_function_body(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _analyse_function_body(self, node: ast.FunctionDef) -> None:
        db_calls_in_fn: list[str] = []

        def _depth(n: ast.AST, d: int = 0) -> int:
            max_d = d
            for child in ast.iter_child_nodes(n):
                if isinstance(child, (ast.If, ast.For, ast.While, ast.Try,
                                      ast.With, ast.AsyncFor, ast.AsyncWith)):
                    max_d = max(max_d, _depth(child, d + 1))
            return max_d

        depth = _depth(node)
        if depth > 4:
            self.deep_nesting.append({
                "file": self.filepath, "function": node.name, "depth": depth,
            })

        _ORM_ATTRS = {"filter", "get", "all", "exclude", "annotate",
                      "aggregate", "values", "objects", "raw", "execute"}
        _HEAVY = {"sorted", "sum", "len", "list", "max", "min"}

        in_loop = [False]

        def _walk(n: ast.AST) -> None:
            is_loop = isinstance(n, (ast.For, ast.While, ast.AsyncFor))
            if is_loop:
                in_loop[0] = True

            if isinstance(n, ast.Call):
                call_str = ast.unparse(n) if hasattr(ast, "unparse") else ""
                # n+1
                if in_loop[0]:
                    if any(attr in call_str for attr in _ORM_ATTRS):
                        self.n_plus_one.append({
                            "file": self.filepath, "line": n.lineno, "detail": call_str[:80],
                        })
                    # heavy recalc
                    if isinstance(n.func, ast.Name) and n.func.id in _HEAVY:
                        self.heavy_loop_recalc.append({
                            "file": self.filepath, "line": n.lineno,
                        })

                # repeated db
                if any(attr in call_str for attr in _ORM_ATTRS):
                    db_calls_in_fn.append(call_str)

                # missing pagination .all()
                if ".all()" in call_str:
                    line_src = self.lines[n.lineno - 1] if n.lineno <= len(self.lines) else ""
                    if "[:\"" not in line_src and ".limit(" not in line_src and "paginate" not in line_src:
                        self.missing_pagination.append({
                            "file": self.filepath, "line": n.lineno,
                        })

            for child in ast.iter_child_nodes(n):
                _walk(child)

            if is_loop:
                in_loop[0] = False

        _walk(node)

        for call, count in Counter(db_calls_in_fn).items():
            if count > 1:
                self.repeated_db_calls.append({
                    "file": self.filepath, "function": node.name, "call": call[:80],
                })

    # ── exceptions ───────────────────────────────────────────────────────────

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.swallowed_exceptions.append({"file": self.filepath, "line": node.lineno})
        elif len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self.swallowed_exceptions.append({"file": self.filepath, "line": node.lineno})
        self.generic_visit(node)

    # ── global mutation ───────────────────────────────────────────────────────

    def visit_Global(self, node: ast.Global) -> None:
        self.global_mutations.append({"file": self.filepath, "line": node.lineno})
        self.generic_visit(node)

    # ── call tracking + credentials + SQL injection ───────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        # track called names (for dead code detection)
        if isinstance(node.func, ast.Name):
            self.called_names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.called_names.add(node.func.attr)

        # SQL injection: string concatenation / f-string in execute()/raw()
        call_str = ast.unparse(node) if hasattr(ast, "unparse") else ""
        if any(m in call_str for m in (".execute(", ".raw(")):
            for arg in node.args:
                if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
                    self.sql_injection.append({"file": self.filepath, "line": node.lineno})
                elif isinstance(arg, ast.JoinedStr):
                    self.sql_injection.append({"file": self.filepath, "line": node.lineno})

        self.generic_visit(node)

    # ── hardcoded credentials ─────────────────────────────────────────────────

    def visit_Assign(self, node: ast.Assign) -> None:
        _CRED_KEYS = {"password", "secret", "api_key", "token", "passwd",
                      "private_key", "auth_token", "access_key"}
        for target in node.targets:
            name = ""
            if isinstance(target, ast.Name):
                name = target.id.lower()
            elif isinstance(target, ast.Attribute):
                name = target.attr.lower()
            if any(k in name for k in _CRED_KEYS):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    val = node.value.value
                    if val and val not in ("", "your-secret", "changeme", "xxx"):
                        self.hardcoded_creds.append({
                            "file": self.filepath, "line": node.lineno, "key": name,
                        })
        self.generic_visit(node)


def _cyclomatic_complexity(tree: ast.AST) -> float:
    """Simple cyclomatic: count branches. 1 + if/elif/for/while/except/and/or."""
    count = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                              ast.AsyncFor, ast.With, ast.AsyncWith)):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
    return float(count)


def _analyse_python(repo_path: Path, files: list[Path]) -> dict:
    all_imports: dict[str, list[str]] = {}
    god_objects: list[dict] = []
    fat_models: list[dict] = []
    mutable_defaults: list[dict] = []
    side_effects: list[dict] = []
    swallowed: list[dict] = []
    global_mut: list[dict] = []
    multi_return: list[dict] = []
    long_fns: list[dict] = []
    deep_nest: list[dict] = []
    n_plus_one: list[dict] = []
    repeated_db: list[dict] = []
    missing_pag: list[dict] = []
    heavy_loop: list[dict] = []
    hardcoded: list[dict] = []
    sql_inj: list[dict] = []
    all_defined: set[str] = set()
    all_called: set[str] = set()
    complexities: list[float] = []
    complexity_hotspots: list[dict] = []

    for fpath in files:
        src = _read(fpath)
        if not src:
            continue
        rel = _rel(fpath, repo_path)
        try:
            tree = ast.parse(src, filename=str(fpath))
        except SyntaxError:
            continue

        cc = _cyclomatic_complexity(tree)
        complexities.append(cc)
        if cc > 10:
            complexity_hotspots.append({"file": rel, "function": rel, "score": cc})

        v = _PythonVisitor(src, rel)
        v.visit(tree)

        module_name = rel.replace("/", ".").replace(".py", "")
        all_imports[module_name] = list(set(v.imports))
        god_objects.extend(v.god_objects)
        fat_models.extend(v.fat_models)
        mutable_defaults.extend(v.mutable_defaults)
        side_effects.extend(v.side_effects_init)
        swallowed.extend(v.swallowed_exceptions)
        global_mut.extend(v.global_mutations)
        multi_return.extend(v.multiple_return_types)
        long_fns.extend(v.long_functions)
        deep_nest.extend(v.deep_nesting)
        n_plus_one.extend(v.n_plus_one)
        repeated_db.extend(v.repeated_db_calls)
        missing_pag.extend(v.missing_pagination)
        heavy_loop.extend(v.heavy_loop_recalc)
        hardcoded.extend(v.hardcoded_creds)
        sql_inj.extend(v.sql_injection)
        all_defined.update(v.defined_names)
        all_called.update(v.called_names)

    # coupling violations
    coupling_violations = [
        {"module": mod, "imports": len(set(imps))}
        for mod, imps in all_imports.items()
        if len(set(imps)) > 7
    ]

    # circular imports
    circular: list[list[str]] = []
    modules = list(all_imports.keys())
    for i, mod_a in enumerate(modules):
        for mod_b in modules[i + 1:]:
            short_b = mod_b.split(".")[-1]
            short_a = mod_a.split(".")[-1]
            if short_b in all_imports.get(mod_a, []) and short_a in all_imports.get(mod_b, []):
                circular.append([mod_a, mod_b])

    # dead code (rough: defined but never called)
    _SKIP_NAMES = {"__init__", "__str__", "__repr__", "__eq__", "__hash__",
                   "main", "setup", "run", "create_app", "get_application"}
    dead = [
        {"name": name, "file": "?", "line": 0}
        for name in all_defined - all_called - _SKIP_NAMES
        if not name.startswith("_")
    ][:20]

    avg_cc = round(sum(complexities) / len(complexities), 2) if complexities else 0.0
    max_cc = round(max(complexities), 2) if complexities else 0.0

    return {
        "cyclomatic_complexity": {
            "avg": avg_cc, "max": max_cc,
            "hotspots": sorted(complexity_hotspots, key=lambda x: -x["score"])[:5],
        },
        "coupling": {"violations": sorted(coupling_violations, key=lambda x: -x["imports"])[:10]},
        "circular_imports": {"pairs": circular[:10]},
        "god_objects": god_objects[:10],
        "fat_models": fat_models[:10],
        "dead_code": dead,
        "mutable_default_args": mutable_defaults[:10],
        "side_effects_in_init": side_effects[:10],
        "swallowed_exceptions": swallowed[:10],
        "global_mutation": global_mut[:10],
        "multiple_return_types": multi_return[:10],
        "long_functions": sorted(long_fns, key=lambda x: -x["lines"])[:10],
        "deep_nesting": sorted(deep_nest, key=lambda x: -x["depth"])[:10],
        "n_plus_one": n_plus_one[:10],
        "repeated_db_calls": repeated_db[:10],
        "missing_pagination": missing_pag[:10],
        "heavy_loop_recalc": heavy_loop[:10],
        "hardcoded_credentials": hardcoded[:10],
        "sql_injection": sql_inj[:10],
    }


# ══════════════════════════════════════════════════════════════════════════════
# JS / TS / VUE — regex-based
# ══════════════════════════════════════════════════════════════════════════════

def _analyse_js_ts(repo_path: Path, files: list[Path]) -> dict:
    god_objects: list[dict] = []
    n_plus_one: list[dict] = []
    missing_pag: list[dict] = []
    swallowed: list[dict] = []
    hardcoded: list[dict] = []
    sql_inj: list[dict] = []
    long_fns: list[dict] = []
    deep_nest: list[dict] = []
    repeated_db: list[dict] = []

    _CRED_RE = re.compile(
        r'(?:password|secret|api_key|token|passwd|private_key|auth_token|access_key)'
        r'\s*[=:]\s*["\']([^"\']{4,})["\']',
        re.IGNORECASE,
    )
    _SQL_INJ_RE = re.compile(
        r'(?:query|execute|raw)\s*\(\s*["`\'][^`"\']*\+',
        re.IGNORECASE,
    )
    # Фикс ReDoS: [^\n]* вместо .* чтобы исключить катастрофический бэктрекинг
    _ORM_IN_LOOP = re.compile(
        r'(?:for\s*\(|\.forEach|\.map|\.filter)\b[^\n]*\n'
        r'(?:[^\n]*\n){0,3}[^\n]*'
        r'(?:await\s+\w+\.\w+\(|prisma\.\w+\.\w+\(|\.findMany|\.findOne|\.find\()',
        re.MULTILINE,
    )
    _ALL_CALL = re.compile(r'\.findMany\(\s*\)|\bfind\(\s*\)|\bfindAll\(\s*\)')
    _CLASS_RE = re.compile(r'class\s+(\w+)', re.MULTILINE)
    _METHOD_RE = re.compile(
        r'(?:async\s+)?(?:public|private|protected|static\s+)*(\w+)\s*\(',
        re.MULTILINE,
    )
    _FN_RE = re.compile(
        r'(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\()',
        re.MULTILINE,
    )
    _CATCH_EMPTY = re.compile(r'catch\s*\(\w+\)\s*\{\s*\}', re.MULTILINE)

    for fpath in files:
        src = _read(fpath)
        if not src:
            continue
        rel = _rel(fpath, repo_path)
        lines = src.splitlines()

        # god objects
        for m in _CLASS_RE.finditer(src):
            cls_name = m.group(1)
            cls_start = src[:m.start()].count("\n")
            cls_src = "\n".join(lines[cls_start:cls_start + 200])
            methods = _METHOD_RE.findall(cls_src)
            if len(methods) > 20:
                god_objects.append({"class": cls_name, "file": rel, "methods": len(methods)})

        # hardcoded creds
        for m in _CRED_RE.finditer(src):
            val = m.group(1)
            if val not in ("", "your-secret", "changeme", "xxx", "password"):
                hardcoded.append({
                    "file": rel,
                    "line": src[:m.start()].count("\n") + 1,
                    "key": m.group(0)[:40],
                })

        # sql injection
        for m in _SQL_INJ_RE.finditer(src):
            sql_inj.append({"file": rel, "line": src[:m.start()].count("\n") + 1})

        # n+1 (ORM in loop)
        for m in _ORM_IN_LOOP.finditer(src):
            n_plus_one.append({
                "file": rel,
                "line": src[:m.start()].count("\n") + 1,
                "detail": m.group(0)[:60],
            })

        # missing pagination
        for m in _ALL_CALL.finditer(src):
            line_no = src[:m.start()].count("\n") + 1
            line_src = lines[line_no - 1] if line_no <= len(lines) else ""
            if "take:" not in line_src and "limit" not in line_src and "paginate" not in line_src:
                missing_pag.append({"file": rel, "line": line_no})

        # swallowed exceptions
        for m in _CATCH_EMPTY.finditer(src):
            swallowed.append({"file": rel, "line": src[:m.start()].count("\n") + 1})

        # long functions (rough: count lines between { and matching })
        for m in _FN_RE.finditer(src):
            start_line = src[:m.start()].count("\n")
            block = "\n".join(lines[start_line:start_line + 200])
            length = min(block.count("\n"), 200)
            if length > 50:
                long_fns.append({"file": rel, "function": m.group(0)[:40], "lines": length})

        # deep nesting: count max consecutive indentation
        max_indent = 0
        for line in lines:
            stripped = line.lstrip()
            if not stripped:
                continue
            indent = (len(line) - len(stripped)) // 2
            max_indent = max(max_indent, indent)
        if max_indent > 4:
            deep_nest.append({"file": rel, "function": rel, "depth": max_indent})

    return {
        "god_objects": god_objects[:10],
        "n_plus_one": n_plus_one[:10],
        "missing_pagination": missing_pag[:10],
        "swallowed_exceptions": swallowed[:10],
        "hardcoded_credentials": hardcoded[:10],
        "sql_injection": sql_inj[:10],
        "long_functions": long_fns[:10],
        "deep_nesting": deep_nest[:10],
        "repeated_db_calls": repeated_db[:10],
        # not applicable for JS/TS:
        "cyclomatic_complexity": {"avg": 0.0, "max": 0.0, "hotspots": []},
        "coupling": {"violations": []},
        "circular_imports": {"pairs": []},
        "fat_models": [],
        "dead_code": [],
        "mutable_default_args": [],
        "side_effects_in_init": [],
        "global_mutation": [],
        "multiple_return_types": [],
        "heavy_loop_recalc": [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# OTHER LANGUAGES — generic regex (Go, Rust, Java, Ruby, PHP, C/C++)
# ══════════════════════════════════════════════════════════════════════════════

def _analyse_generic(repo_path: Path, files: list[Path]) -> dict:
    """Minimal but cross-language: credentials, SQL injection, long functions, deep nesting."""
    hardcoded: list[dict] = []
    sql_inj: list[dict] = []
    long_fns: list[dict] = []
    deep_nest: list[dict] = []

    _CRED_RE = re.compile(
        r'(?:password|secret|api_key|token|passwd|private_key)'
        r'\s*[=:]\s*["\']([^"\']{4,})["\']',
        re.IGNORECASE,
    )
    _SQL_RE = re.compile(
        r'(?:query|execute|Exec|db\.Raw)\s*\(\s*["`][^`"]*\+',
        re.IGNORECASE,
    )

    for fpath in files:
        src = _read(fpath)
        if not src:
            continue
        rel = _rel(fpath, repo_path)
        lines = src.splitlines()

        for m in _CRED_RE.finditer(src):
            val = m.group(1)
            if val not in ("", "your-secret", "changeme"):
                hardcoded.append({
                    "file": rel,
                    "line": src[:m.start()].count("\n") + 1,
                    "key": m.group(0)[:40],
                })

        for m in _SQL_RE.finditer(src):
            sql_inj.append({"file": rel, "line": src[:m.start()].count("\n") + 1})

        max_indent = 0
        for line in lines:
            stripped = line.lstrip()
            if not stripped:
                continue
            indent = len(line) - len(stripped)
            max_indent = max(max_indent, indent // 4)
        if max_indent > 4:
            deep_nest.append({"file": rel, "function": rel, "depth": max_indent})

    empty: dict[str, Any] = {
        "cyclomatic_complexity": {"avg": 0.0, "max": 0.0, "hotspots": []},
        "coupling": {"violations": []},
        "circular_imports": {"pairs": []},
        "god_objects": [],
        "fat_models": [],
        "dead_code": [],
        "mutable_default_args": [],
        "side_effects_in_init": [],
        "swallowed_exceptions": [],
        "global_mutation": [],
        "multiple_return_types": [],
        "long_functions": long_fns[:10],
        "deep_nesting": deep_nest[:10],
        "n_plus_one": [],
        "repeated_db_calls": [],
        "missing_pagination": [],
        "heavy_loop_recalc": [],
        "hardcoded_credentials": hardcoded[:10],
        "sql_injection": sql_inj[:10],
    }
    return empty


# ══════════════════════════════════════════════════════════════════════════════
# MERGE results from multiple language analysers
# ══════════════════════════════════════════════════════════════════════════════

_METRIC_KEYS = [
    "cyclomatic_complexity", "coupling", "circular_imports",
    "god_objects", "fat_models", "dead_code",
    "mutable_default_args", "side_effects_in_init", "swallowed_exceptions",
    "global_mutation", "multiple_return_types", "long_functions", "deep_nesting",
    "n_plus_one", "repeated_db_calls", "missing_pagination", "heavy_loop_recalc",
    "hardcoded_credentials", "sql_injection",
]

# delta metrics (20-23) are computed externally from two snapshots
_DELTA_KEYS = [
    "coupling_delta", "complexity_delta", "circular_import_new", "god_object_new",
]


def _merge(results: list[dict]) -> dict:
    merged: dict[str, Any] = {}
    for key in _METRIC_KEYS:
        sample = results[0].get(key) if results else None
        if isinstance(sample, dict):
            merged[key] = sample
            for r in results[1:]:
                v = r.get(key, {})
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        if isinstance(v2, list):
                            merged[key][k2] = merged[key].get(k2, []) + v2
                        elif isinstance(v2, (int, float)):
                            merged[key][k2] = max(merged[key].get(k2, 0), v2)
        elif isinstance(sample, list):
            acc: list = []
            for r in results:
                acc.extend(r.get(key, []))
            merged[key] = acc[:20]
        else:
            merged[key] = sample
    return merged


def _compute_flags(metrics: dict) -> dict:
    flags: dict[str, str] = {}

    cc = metrics.get("cyclomatic_complexity", {})
    flags["cyclomatic_complexity"] = _flag_value(cc.get("max", 0), 7, 10)
    flags["coupling"] = _flag(metrics.get("coupling", {}).get("violations", []), 1, 3)
    flags["circular_imports"] = _flag(metrics.get("circular_imports", {}).get("pairs", []), 1, 2)
    flags["god_objects"] = _flag(metrics.get("god_objects", []), 1, 3)
    flags["fat_models"] = _flag(metrics.get("fat_models", []), 1, 2)
    flags["dead_code"] = _flag(metrics.get("dead_code", []), 3, 10)
    flags["mutable_default_args"] = _flag(metrics.get("mutable_default_args", []), 1, 3)
    flags["side_effects_in_init"] = _flag(metrics.get("side_effects_in_init", []), 1, 2)
    flags["swallowed_exceptions"] = _flag(metrics.get("swallowed_exceptions", []), 1, 3)
    flags["global_mutation"] = _flag(metrics.get("global_mutation", []), 1, 3)
    flags["multiple_return_types"] = _flag(metrics.get("multiple_return_types", []), 2, 5)
    flags["long_functions"] = _flag(metrics.get("long_functions", []), 2, 5)
    flags["deep_nesting"] = _flag(metrics.get("deep_nesting", []), 1, 3)
    flags["n_plus_one"] = _flag(metrics.get("n_plus_one", []), 1, 2)
    flags["repeated_db_calls"] = _flag(metrics.get("repeated_db_calls", []), 1, 3)
    flags["missing_pagination"] = _flag(metrics.get("missing_pagination", []), 1, 3)
    flags["heavy_loop_recalc"] = _flag(metrics.get("heavy_loop_recalc", []), 1, 3)
    flags["hardcoded_credentials"] = _flag(metrics.get("hardcoded_credentials", []), 1, 1)
    flags["sql_injection"] = _flag(metrics.get("sql_injection", []), 1, 1)

    return flags


def compute_delta(current: dict, previous: dict | None) -> dict:
    """Metrics 20-23: structural delta between two quality snapshots."""
    if previous is None:
        return {k: None for k in _DELTA_KEYS}

    cur_coup = len(current.get("coupling", {}).get("violations", []))
    prev_coup = len(previous.get("coupling", {}).get("violations", []))
    cur_cc = current.get("cyclomatic_complexity", {}).get("avg", 0)
    prev_cc = previous.get("cyclomatic_complexity", {}).get("avg", 0)
    cur_circ = set(map(tuple, current.get("circular_imports", {}).get("pairs", [])))
    prev_circ = set(map(tuple, previous.get("circular_imports", {}).get("pairs", [])))
    cur_gods = {g["class"] for g in current.get("god_objects", [])}
    prev_gods = {g["class"] for g in previous.get("god_objects", [])}

    return {
        "coupling_delta": {
            "before": prev_coup, "after": cur_coup,
            "direction": "up" if cur_coup > prev_coup else "down" if cur_coup < prev_coup else "neutral",
            "flag": "red" if cur_coup > prev_coup else "green",
        },
        "complexity_delta": {
            "before": round(prev_cc, 2), "after": round(cur_cc, 2),
            "direction": "up" if cur_cc > prev_cc else "down" if cur_cc < prev_cc else "neutral",
            "flag": "red" if cur_cc > prev_cc + 1 else "green",
        },
        "circular_import_new": {
            "new_pairs": [list(p) for p in cur_circ - prev_circ],
            "flag": "red" if cur_circ - prev_circ else "green",
        },
        "god_object_new": {
            "new_classes": list(cur_gods - prev_gods),
            "flag": "red" if cur_gods - prev_gods else "green",
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def run(
    repo: GitRepo,
    config: Config,
    stack: StackInfo,
    tools: ToolCheckResult,
    prev_snapshot: dict | None = None,
) -> dict:
    repo_path = repo.path
    all_results: list[dict] = []

    py_exts = {".py"}
    js_exts = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue"}
    other_exts = {".go", ".rs", ".java", ".kt", ".rb", ".php", ".c", ".cpp", ".cc", ".h", ".hpp"}

    source_exts = set(stack.source_extensions)

    py_files = _source_files(repo_path, list(source_exts & py_exts))
    js_files = _source_files(repo_path, list(source_exts & js_exts))
    other_files = _source_files(repo_path, list(source_exts & other_exts))

    if py_files:
        all_results.append(_analyse_python(repo_path, py_files))
    if js_files:
        all_results.append(_analyse_js_ts(repo_path, js_files))
    if other_files:
        all_results.append(_analyse_generic(repo_path, other_files))

    if not all_results:
        metrics: dict = {k: [] for k in _METRIC_KEYS}
        metrics["cyclomatic_complexity"] = {"avg": 0.0, "max": 0.0, "hotspots": []}
        metrics["coupling"] = {"violations": []}
        metrics["circular_imports"] = {"pairs": []}
    else:
        metrics = _merge(all_results)

    flags = _compute_flags(metrics)
    delta = compute_delta(metrics, prev_snapshot)

    return {
        "metrics": metrics,
        "delta": delta,
        "flags": flags,
        "languages_analysed": (
            (["Python"] if py_files else []) +
            (["JS/TS/Vue"] if js_files else []) +
            (["other"] if other_files else [])
        ),
        "inline_comments": repo.scan_inline_comments(stack.comment_prefix_map),
    }
