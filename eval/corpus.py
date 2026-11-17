"""Build oracle-labelled mutation cases on real production Python modules.

This is the public development generator. Reserved holdout variants are private.
No production detector helper or output is used to construct oracle labels.
"""

from __future__ import annotations

import ast
from dataclasses import asdict
import io
import json
import os
import re
from pathlib import Path
import subprocess
import tarfile
import tempfile
import tokenize

from .oracle import occurrence, run


def git(path, *args):
    output = subprocess.check_output(["git", *args], cwd=path, stderr=subprocess.PIPE, env={**os.environ,"GIT_AUTHOR_DATE":"2000-01-01T00:00:00+0000","GIT_COMMITTER_DATE":"2000-01-01T00:00:00+0000","GIT_OPTIONAL_LOCKS":"0"}).decode()
    return output if args and args[0] == "diff" else output.strip()


def export(repo, sha, destination):
    """Materialize a tracked Git tree without checkout/index/ref changes."""
    destination.mkdir(parents=True, exist_ok=True)
    content = subprocess.check_output(["git", "archive", sha], cwd=repo)
    with tarfile.open(fileobj=io.BytesIO(content)) as archive:
        archive.extractall(destination, filter="data")


def module_for(path, roots):
    for root in roots:
        prefix = root.removesuffix(".py").rstrip("/")
        if root.endswith(".py") and path == root:
            return Path(path).stem
        if path.startswith(prefix + "/") and path.endswith(".py"):
            # roots point at packages, so preserve the final root component.
            parts = [Path(prefix).name, *Path(path[len(prefix) + 1:]).with_suffix("").parts]
            if parts[-1] == "__init__":
                parts.pop()
            if all(part.isidentifier() for part in parts):
                return ".".join(parts)
    return None


def candidates(repo, roots):
    """Find existing undecorated module functions, preferring small isolated APIs."""
    found = []
    for root in roots:
        source_root = repo / root
        paths = [source_root] if source_root.is_file() else sorted(source_root.rglob("*.py"))
        for file in paths:
            relative = file.relative_to(repo).as_posix()
            module = module_for(relative, roots)
            if module is None or any("test" in part for part in Path(relative).parts) or relative.endswith("__init__.py"):
                continue
            source = file.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.decorator_list or node.name.startswith("__"):
                    continue
                args = node.args
                positional = [*args.posonlyargs, *args.args]
                if args.vararg or args.kwarg or len(positional) > 5:
                    continue
                found.append({"path": relative, "module": module, "name": node.name, "source": source,
                              "line": node.lineno, "end_line": node.end_lineno,
                              "node": node, "async": isinstance(node, ast.AsyncFunctionDef)})
    return sorted(found, key=lambda item: (len(item["source"]), item["path"], item["name"]))


def call_source(candidate, family, control=False):
    """Generate an actually typechecked use of the real function, with Any values."""
    node = candidate["node"]
    args = node.args
    values = ["cast(Any, None)" for _ in [*args.posonlyargs, *args.args]]
    keywords = [f"{arg.arg}=cast(Any, None)" for arg in args.kwonlyargs]
    if family == "unknown_keyword":
        # Pass the last ordinary parameter by keyword to exercise a rename.
        if args.args:
            values.pop()
            keywords.insert(0, f"{args.args[-1].arg}=cast(Any, None)")
    if family == "required_posonly":
        # Existing keyword calls become invalid after the real parameter becomes positional-only.
        if args.args:
            values.pop()
            keywords.insert(0, f"{args.args[-1].arg}=cast(Any, None)")
    expression = f"module.{candidate['name']}({', '.join([*values, *keywords])})"
    statement = f"await {expression}" if candidate["async"] else expression
    return (f"from typing import Any, cast\nimport {candidate['module']} as module\n\n"
            + ("async " if candidate["async"] else "") + f"def check_use() -> None:\n    {statement}\n")


def mutate(candidate, family):
    """Edit a real declaration; individual tips must pass before any case is accepted."""
    if family == "remove_reexport":
        return candidate["source"]
    tree = ast.parse(candidate["source"])
    node = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == candidate["name"]), None)
    if node is None:
        if family == "optional_keyword":
            return candidate["source"] + "\ncrosswire_optional_export = 0\n"
        return re.sub(r"\b" + re.escape(candidate["name"]) + r"\b", "crosswire_replacement_" + candidate["name"], candidate["source"]) if family == "rename_attribute" else None
    if family == "module_move":
        return candidate["source"]
    if family in {"remove_attribute", "rename_attribute"}:
        # Preserve implementation under a replacement name so A can update its own consumers.
        node.name = "crosswire_replacement_" + node.name
    elif family == "required_positional":
        # Keyword-only avoids invalid 'non-default after default' declarations.
        node.args.kwonlyargs.append(ast.arg(arg="crosswire_required", annotation=ast.Name(id="int", ctx=ast.Load())))
        node.args.kw_defaults.append(None)
    elif family == "required_keyword":
        node.args.kwonlyargs.append(ast.arg(arg="template", annotation=ast.Name(id="str", ctx=ast.Load())))
        node.args.kw_defaults.append(None)
    elif family == "optional_keyword":
        node.args.kwonlyargs.append(ast.arg(arg="crosswire_optional", annotation=ast.Name(id="int", ctx=ast.Load())))
        node.args.kw_defaults.append(ast.Constant(value=0))
    elif family == "unknown_keyword":
        if not node.args.args:
            return None
        old = node.args.args[-1].arg
        node.args.args[-1].arg = "crosswire_new_name"
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id == old:
                child.id = "crosswire_new_name"
    elif family == "too_many_positional":
        # Keep the original name bound in the body through a keyword-only argument.
        if not node.args.args:
            return None
        moved = node.args.args.pop()
        default = node.args.defaults.pop() if node.args.defaults else None
        node.args.kwonlyargs.insert(0, moved)
        node.args.kw_defaults.insert(0, default)
    elif family == "required_posonly":
        if not node.args.args:
            return None
        node.args.posonlyargs.extend(node.args.args)
        node.args.args = []
    else:
        raise ValueError(family)
    # Preserve body comments/type-ignore pragmas; only the declaration header changes.
    lines = candidate["source"].splitlines(keepends=True)
    original = "".join(lines[candidate["line"] - 1:candidate["end_line"]])
    depth = 0
    colon = None
    for token in tokenize.generate_tokens(io.StringIO(original).readline):
        if token.type == tokenize.OP:
            if token.string in "([{":
                depth += 1
            elif token.string in ")]}":
                depth -= 1
            elif token.string == ":" and depth == 0:
                colon = token.end
                break
    if colon is None:
        return None
    original_lines = original.splitlines(keepends=True)
    rest = original_lines[colon[0] - 1][colon[1]:] + "".join(original_lines[colon[0]:])
    if family == "unknown_keyword":
        rest = re.sub(r"\b" + re.escape(candidate["node"].args.args[-1].arg) + r"\b", "crosswire_new_name", rest)
    header = ast.unparse(ast.fix_missing_locations(node)).splitlines()[0]
    replacement = header + rest
    if not replacement.endswith("\n"):
        replacement += "\n"
    return "".join(lines[:candidate["line"] - 1]) + replacement + "".join(lines[candidate["end_line"]:])


def create_repo(screen, directory):
    """Create an isolated full-history case repository from the pinned upstream tree."""
    directory.mkdir(parents=True)
    export(Path(screen["path"]), screen.get("archive_sha", screen["sha"]), directory)
    git(directory, "init", "-b", "main")
    git(directory, "config", "user.name", "Crosswire Evaluation")
    git(directory, "config", "user.email", "eval@invalid")
    git(directory, "config", "commit.gpgSign", "false")
    hooks = directory.parent / (directory.name + "-hooks")
    hooks.mkdir(exist_ok=True)
    git(directory, "config", "core.hooksPath", str(hooks))
    git(directory, "add", "-A")
    git(directory, "commit", "-m", "pinned upstream target")


def update_internal_uses(directory, screen, candidate, family):
    """Keep refactoring tips green by updating pre-existing production call sites.

    A newly added caller on B is deliberately absent from this coordinated A edit.
    The full oracle still checks the result; uncertain rewrites are rejected.
    """
    if family == "module_move":
        original = directory / candidate["path"]
        new_stem = "crosswire_moved_" + original.stem
        original.rename(original.with_name(new_stem + ".py"))
    from .oracle import scope
    for root in scope(directory, screen["roots"]):
        source_root = directory / root
        files = [source_root] if source_root.is_file() else source_root.rglob("*.py")
        for file in files:
            source = file.read_text()
            if family == "module_move":
                old_stem = Path(candidate["path"]).stem
                file.write_text(re.sub(r"\b" + re.escape(old_stem) + r"\b", "crosswire_moved_" + old_stem, source))
                continue
            if family in {"rename_attribute", "remove_attribute", "remove_reexport"}:
                updated = re.sub(r"\b" + re.escape(candidate["name"]) + r"\b", "crosswire_replacement_" + candidate["name"], source)
                if updated != source:
                    file.write_text(updated)
                continue
            if family not in {"required_keyword", "required_positional", "unknown_keyword", "too_many_positional", "required_posonly"}:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            changed = False
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
                if name != candidate["name"]:
                    continue
                old_args = candidate["node"].args
                if family == "unknown_keyword" and old_args.args:
                    old_name = old_args.args[-1].arg
                    for keyword in node.keywords:
                        if keyword.arg == old_name:
                            keyword.arg = "crosswire_new_name"
                            changed = True
                elif family == "too_many_positional" and old_args.args:
                    position = len(old_args.posonlyargs) + len(old_args.args) - 1
                    if len(node.args) > position:
                        node.keywords.append(ast.keyword(arg=old_args.args[-1].arg, value=node.args.pop(position)))
                        changed = True
                elif family == "required_posonly":
                    for argument in [*old_args.posonlyargs, *old_args.args]:
                        for keyword in list(node.keywords):
                            if keyword.arg == argument.arg:
                                node.args.append(keyword.value)
                                node.keywords.remove(keyword)
                                changed = True
                else:
                    parameter = "template" if family == "required_keyword" else "crosswire_required"
                    if not any(keyword.arg == parameter for keyword in node.keywords):
                        node.keywords.append(ast.keyword(arg=parameter, value=ast.Constant(value="" if family == "required_keyword" else 0)))
                        changed = True
            if changed:
                if family in {"required_keyword", "required_positional"}:
                    parameter = "template" if family == "required_keyword" else "crosswire_required"
                    value = '""' if family == "required_keyword" else "0"
                    encoded = source.encode()
                    source_lines = source.splitlines(keepends=True)
                    patches = []
                    for call in ast.walk(ast.parse(source)):
                        if not isinstance(call, ast.Call):
                            continue
                        call_name = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else None
                        if call_name != candidate["name"] or any(k.arg == parameter for k in call.keywords):
                            continue
                        offset = len("".join(source_lines[:call.end_lineno - 1]).encode()) + call.end_col_offset - 1
                        before = encoded[:offset].rstrip()
                        separator = "" if before.endswith((b"(", b",")) else ", "
                        patches.append((offset, f"{separator}{parameter}={value}".encode()))
                    for offset, addition in sorted(patches, reverse=True):
                        encoded = encoded[:offset] + addition + encoded[offset:]
                    file.write_bytes(encoded)
                else:
                    file.write_text(ast.unparse(ast.fix_missing_locations(tree)) + "\n")


def build_case(screen, candidate, family, kind, directory, python, checker):
    """Return labelled case evidence only after checking target, tips and clean merge."""
    create_repo(screen, directory)
    consumer = "crosswire_eval_use.py"
    source = call_source(candidate, family)
    roots = [*screen["roots"], consumer]
    original = candidate["source"]
    changed = mutate(candidate, family)
    if changed is None:
        return None
    # Controls: stable API + unrelated edit; both sides agree on renamed API; no API change.
    if kind == "unrelated":
        changed = original + "\n# independently edited documentation\n"
    elif kind == "compatible":
        changed = mutate(candidate, "optional_keyword")
    elif kind == "coordinated":
        changed = mutate(candidate, "rename_attribute")
        source = source.replace(f"module.{candidate['name']}(", f"module.crosswire_replacement_{candidate['name']}(")
    target = git(directory, "rev-parse", "HEAD")
    base_oracle = run(directory, roots, python, checker)
    # The future consumer path may not exist at target; keep it absent everywhere except B.
    git(directory, "checkout", "-b", "A")
    (directory / candidate["path"]).write_text(changed)
    if kind == "positive":
        update_internal_uses(directory, screen, candidate, family)
    elif kind == "coordinated":
        update_internal_uses(directory, screen, candidate, "rename_attribute")
    git(directory, "add", "--all")
    git(directory, "commit", "-m", family + " " + kind)
    first = git(directory, "rev-parse", "HEAD")
    first_oracle = run(directory, roots, python, checker)
    git(directory, "checkout", "-b", "B", target)
    (directory / consumer).write_text(source)
    # Coordinated control: B uses the new API and independently applies the identical rename.
    if kind == "coordinated":
        (directory / candidate["path"]).write_text(changed)
        update_internal_uses(directory, screen, candidate, "rename_attribute")
        git(directory, "add", "--all")
    git(directory, "add", consumer)
    git(directory, "commit", "-m", "new real API use")
    second = git(directory, "rev-parse", "HEAD")
    second_oracle = run(directory, roots, python, checker)
    result = subprocess.run(["git", "merge-tree", "--write-tree", "A", "B"], cwd=directory, capture_output=True, text=True)
    if result.returncode:
        return {"eligible": False, "exclusion": "textual conflict", "family": family, "kind": kind}
    tree = result.stdout.splitlines()[0]
    merged = git(directory, "-c", "commit.gpgSign=false", "commit-tree", tree, "-p", first, "-p", second, "-m", "oracle merge")
    git(directory, "checkout", "--detach", merged)
    final_oracle = run(directory, roots, python, checker)
    parent_oracles = (base_oracle, first_oracle, second_oracle)
    eligible = all(item.status == "pass" for item in parent_oracles) and final_oracle.status != "unlabelled"
    errors = [d for d in final_oracle.diagnostics if Path(d["file"]).name == consumer and d.get("rule") in {"reportAttributeAccessIssue", "reportCallIssue", "reportMissingImports"}]
    expected_positive = kind == "positive"
    if eligible and expected_positive and not errors:
        eligible = False
    if eligible and not expected_positive and final_oracle.status != "pass":
        eligible = False
    line = 5
    symbol = f"{candidate['module']}.{candidate['name']}"
    return {"repository": screen["repository"], "upstream_sha": screen["sha"], "roots": screen["roots"],
            "family": family, "kind": kind, "path": str(directory), "eligible": eligible,
            "exclusion": None if eligible else "target/tip not green or no attributable oracle result",
            "target": target, "tips": {"A": first, "B": second}, "integrated": merged,
            "symbol": symbol, "module_path": candidate["path"], "consumer": consumer, "line": line,
            "occurrence": occurrence(source, line, symbol), "type": "PY-3" if family == "remove_reexport" else "PY-2" if family == "module_move" else "PY-1" if family in {"remove_attribute", "rename_attribute"} else "PY-4",
            "oracle": {name: asdict(value) for name, value in zip(("target", "A", "B", "integrated"), (*parent_oracles, final_oracle))},
            "oracle_positive": bool(errors), "attribution_oracle": True if eligible and expected_positive else None,
            "patch": git(directory, "diff", target, first, "--", candidate["path"]), "consumer_source": source}
