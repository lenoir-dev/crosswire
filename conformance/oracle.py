"""Pinned Pyright plus focused runtime use checks, independent of the detector."""
import hashlib
import json
from pathlib import Path
import subprocess

from .git import environment, write_files


PIN = "1.1.407"
CONFIG = {"typeCheckingMode":"basic", "pythonVersion":"3.11", "include":["."],
          "reportMissingImports":"error", "reportAttributeAccessIssue":"error", "reportCallIssue":"error"}


class KitBug(RuntimeError):
    """The template/oracle/fixture disagrees; it cannot certify conformance."""


def checker_env():
    env = environment()
    env.update(PYRIGHT_PYTHON_FORCE_VERSION=PIN, PYRIGHT_PYTHON_IGNORE_WARNINGS="1")
    return env


def checker_provenance(python):
    # Installation comes from the eval group; an unavailable/wrong pin is a kit
    # error, never a negative control. No production modules are imported.
    script = ("import importlib.metadata,json,sys; from pyright import node; "
              "from pyright._utils import install_pyright; "
              "binary=json.loads(node.run('node','-p','JSON.stringify({path:process.execPath,version:process.version})',capture_output=True).stdout); "
              "print(json.dumps({'package_version':importlib.metadata.version('pyright'),"
              "'bundle':str(install_pyright([],quiet=True)),'python_version':sys.version,'node':binary}))")
    result = subprocess.run([python, "-I", "-c", script], env=checker_env(), capture_output=True, timeout=120)
    if result.returncode:
        raise KitBug("Pinned Pyright unavailable; install the eval group")
    data = json.loads(result.stdout)
    if data["package_version"] != PIN:
        raise KitBug("Pyright Python package is not " + PIN)
    bundle = Path(data.pop("bundle"))
    node = data.pop("node")
    data.update(node_version=node["version"],node_sha256=hashlib.sha256(Path(node["path"]).read_bytes()).hexdigest())
    digest = hashlib.sha256()
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(bundle).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    version = subprocess.run([python,"-I","-m","pyright","--version"],env=checker_env(),capture_output=True,timeout=30)
    if version.returncode or version.stdout.decode().strip() != "pyright " + PIN:
        raise KitBug("Wrong checker engine version")
    data.update(bundle_sha256=digest.hexdigest(), python_sha256=hashlib.sha256(Path(python).resolve().read_bytes()).hexdigest(),
                config=CONFIG, version=PIN)
    return data


def check(files, directory, python):
    directory.mkdir(parents=True)
    write_files(directory, files)
    config = directory / ".conformance-pyright.json"
    config.write_text(json.dumps(CONFIG, sort_keys=True, indent=2) + "\n")
    command = [python, "-I", "-m", "pyright", "--outputjson", "--pythonpath", python, "--project", str(config)]
    try:
        result = subprocess.run(command, cwd=directory, env=checker_env(), capture_output=True, timeout=60)
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError) as error:
        raise KitBug("Oracle execution failed: " + type(error).__name__) from error
    diagnostics = data.get("generalDiagnostics")
    if result.returncode not in (0,1) or data.get("version") != PIN or not isinstance(diagnostics,list):
        raise KitBug("Wrong/incomplete checker output")
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    summary = data.get("summary", {})
    if summary.get("filesAnalyzed") != len(files) or summary.get("errorCount") != len(errors):
        raise KitBug("Oracle did not analyze every rendered file or truncated its errors")
    if (result.returncode == 0) != (len(errors) == 0):
        raise KitBug("Oracle exit/error disagreement")
    normalized = []
    for error in errors:
        path = Path(error["file"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise KitBug("Diagnostic outside rendered source")
        normalized.append({**error, "file":path.relative_to(directory).as_posix()})
    runtime_script = (
        "import pathlib,runpy,sys; root=pathlib.Path(sys.argv[1]); sys.path.insert(0,str(root)); "
        "consumers=sorted(root.glob('consumer*.py')); "
        "[runpy.run_path(str(p),run_name='__main__') for p in consumers]"
    )
    runtime = subprocess.run([python,"-I","-B","-c",runtime_script,str(directory)],cwd=directory,
                             env=checker_env(),capture_output=True,timeout=30)
    if runtime.returncode not in (0,1):
        raise KitBug("Runtime probe had an operational failure")
    return {"verdict":"broken" if errors else "valid", "exit":result.returncode,
            "files_analyzed":summary["filesAnalyzed"], "diagnostics":normalized,
            "checker_stderr":result.stderr.decode("utf-8", "replace"),
            "runtime":{"verdict":"valid" if runtime.returncode==0 else "broken", "exit":runtime.returncode,
                       "stdout":runtime.stdout.decode("utf-8", "replace"), "stderr":runtime.stderr.decode("utf-8", "replace")}}


def validate(case, observations, sites):
    expected_bad = set(case["oracle"]["broken_states"])
    if not expected_bad <= observations.keys():
        raise KitBug("Template declares an unrendered oracle state")
    for state, result in observations.items():
        expected = "broken" if state in expected_bad else "valid"
        if result["verdict"] != expected or result["runtime"]["verdict"] != expected:
            raise KitBug(f"Oracle/template disagreement at {state}: expected {expected}, checker {result['verdict']}, runtime {result['runtime']['verdict']}")
        for error in result["diagnostics"]:
            if error.get("rule") not in case["oracle"]["categories"]:
                raise KitBug("Unsupported/unexpected checker category: " + str(error.get("rule")))
            site = sites[case["oracle"]["site"]]
            line = error["range"]["start"]["line"] + 1
            if error["file"] != site["path"] or not site["start_line"] <= line <= site["end_line"]:
                raise KitBug("Oracle error is at a different use site")
    labels = [b["id"] for b in case["branches"]]
    pair_broken = any("+" in state and len(state.split("+"))==2 and r["verdict"]=="broken" for state,r in observations.items())
    full_broken = observations["+".join(labels)]["verdict"] == "broken"
    derived = {"pairwise":"broken" if pair_broken else "valid", "combined":"broken" if full_broken else "valid",
               "plan":"broken" if full_broken else "valid"}
    if case["proof"] == "open":
        if expected_bad:
            raise KitBug("Open-boundary template unexpectedly claims an oracle conflict")
        derived = {m:"unknown" for m in derived}
    if derived != {m:e["verdict"] for m,e in case["expected"].items()}:
        raise KitBug("Declared per-mode verdicts disagree with independent oracle states/contract boundary")
