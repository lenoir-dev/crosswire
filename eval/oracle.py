"""Pinned full-source Pyright oracle; labels never depend on crosswire output."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess


POLICY = json.loads(Path(__file__).with_name("policy.json").read_text())


@dataclass(frozen=True)
class OracleResult:
    status: str
    diagnostics: tuple[dict, ...]
    reason: str | None
    command: tuple[str, ...]


def scope(root, roots):
    """Include every repository test directory, without excluding production roots."""
    tests = sorted({p.as_posix() for p in Path(root).rglob("*") if p.is_dir() and (p.name in {"test", "tests", "testing", "testsuite", "_tests"}) and not any(part.startswith(".") for part in p.relative_to(root).parts)})
    files = sorted(p.relative_to(root).as_posix() for p in Path(root).glob("test*.py"))
    return list(dict.fromkeys([*roots, *(Path(p).relative_to(root).as_posix() for p in tests), *files]))


def run(root: Path, roots: list[str], python: str, checker: str, timeout=60) -> OracleResult:
    """Check production and test sources with identical pinned basic config."""
    config = {**POLICY["oracle"], "include": scope(root, roots)}
    path = root / ".crosswire-eval-pyright.json"
    path.write_text(json.dumps(config, sort_keys=True, indent=2) + "\n")
    command = (checker, "--outputjson", "--pythonpath", python, "--project", str(path))
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                timeout=timeout, env={**os.environ, "PYRIGHT_PYTHON_FORCE_VERSION": POLICY["pyright"], "PYRIGHT_PYTHON_IGNORE_WARNINGS":"1"})
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        return OracleResult("unlabelled", (), type(exc).__name__, command)
    if not isinstance(data, dict) or result.returncode not in (0, 1) or not isinstance(data.get("summary"), dict):
        return OracleResult("unlabelled", (), "checker failed", command)
    diagnostics = data.get("generalDiagnostics")
    if not isinstance(diagnostics, list) or any(not isinstance(d, dict) for d in diagnostics):
        return OracleResult("unlabelled", (), "incomplete checker diagnostics", command)
    errors = tuple(d for d in diagnostics if d.get("severity") == "error")
    if data.get("version") != POLICY["pyright"]:
        return OracleResult("unlabelled", errors, "checker version mismatch", command)
    if not data["summary"].get("filesAnalyzed") or data["summary"].get("errorCount") != len(errors):
        return OracleResult("unlabelled", errors, "empty or incomplete checker coverage", command)
    if result.returncode == 0 and errors:
        return OracleResult("unlabelled", errors, "inconsistent checker exit code", command)
    return OracleResult("pass" if not errors else "fail", errors, None, command)


def occurrence(source: str, line: int, symbol: str) -> str:
    """Fingerprint the call/reference expression at an oracle use site, ignoring offsets."""
    tree = ast.parse(source)
    matches = [node for node in ast.walk(tree) if isinstance(node, (ast.Call, ast.Import, ast.ImportFrom, ast.Attribute))
               and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)]
    name = symbol.rsplit(".", 1)[-1]
    calls = [node for node in matches if isinstance(node, ast.Call) and (
        isinstance(node.func, ast.Name) and node.func.id == name
        or isinstance(node.func, ast.Attribute) and node.func.attr == name)]
    selected = min(calls or matches, key=lambda node: len(ast.dump(node)), default=None)
    def stable(node):
        if isinstance(node, ast.AST):
            return {"node": type(node).__name__, **{field: stable(value) for field, value in ast.iter_fields(node)
                                                     if value is not None and value != []}}
        if isinstance(node, list):
            return [stable(value) for value in node]
        return node
    # ast.dump omits empty fields by default on newer Python versions; use our own encoding.
    content = json.dumps(stable(selected), sort_keys=True, separators=(",", ":")) if selected else "unresolved"
    same = []
    if selected is not None:
        encoded = json.dumps(stable(selected),sort_keys=True,separators=(",", ":"))
        same = sorted((n.lineno, n.col_offset) for n in ast.walk(tree) if type(n) is type(selected) and json.dumps(stable(n),sort_keys=True,separators=(",", ":")) == encoded)
    ordinal = same.index((selected.lineno, selected.col_offset)) if selected is not None else 0
    return hashlib.sha256((symbol + "\0" + content + "\0" + str(ordinal)).encode()).hexdigest()


def reason_category(text: str) -> str | None:
    """Map checker/detector prose to M1's diagnostic quality categories."""
    text = text.lower()
    if "positional-only" in text or "positional only" in text:
        return "positional-only"
    if "no parameter named" in text or "unknown keyword" in text or "unexpected keyword" in text:
        return "unknown keyword"
    if "too many positional" in text or "positional argument" in text and "expected" in text:
        return "too many positional"
    if "missing" in text or "argument missing" in text:
        return "missing"
    return None
