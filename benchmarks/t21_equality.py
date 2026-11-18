"""T21a immutable raw CLI differential gate (no output projections).

First record (explicit, refuses replacement):
  python benchmarks/t21_equality.py --baseline /tmp/release --candidate . --record-baseline
Replay both sources against the immutable recording:
  python benchmarks/t21_equality.py --baseline /tmp/release --candidate .

Release pytest inputs and all observed CLI invocations are harvested once. Every
fixture additionally runs pairwise/combined × four formats and plan × two, both
branch orders and five cache states. Expected bytes live in gzip JSONL as base64;
JSON encoding is a transport only, never a projection of the CLI output.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "docs/validation/t21-baseline"
FIXTURE_ROOT = Path("/tmp/crosswire-t21a-fixtures").resolve()
BOOTSTRAP = (
    "import sys,pathlib,runpy; source=pathlib.Path(sys.argv.pop(1)).resolve(); "
    "sys.path.insert(0,str(source)); import crosswire; "
    "assert pathlib.Path(crosswire.__file__).resolve().is_relative_to(source); "
    "sys.argv[0]='crosswire'; runpy.run_module('crosswire',run_name='__main__',alter_sys=True)"
)
CACHES = ("no-cache", "cold", "warm", "preseeded", "malformed")
FORMATS = {"pairwise": ("text", "json", "github", "sarif"),
           "combined": ("text", "json", "github", "sarif"), "plan": ("text", "json")}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def source_hashes(checkout):
    source = Path(checkout) / "src"
    if not (source / "crosswire/__init__.py").is_file():
        raise ValueError("Checkout must contain src/crosswire")
    return {p.relative_to(checkout).as_posix(): sha(p.read_bytes())
            for p in sorted(source.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def environment(fake_git=None):
    result = dict(os.environ)
    for key in list(result):
        if key.startswith(("GIT_", "CROSSWIRE_", "PYTEST_", "PYTHON")):
            result.pop(key)
    result.update(LC_ALL="C", LANG="C", TZ="UTC", PYTHONHASHSEED="0",
                  PYTHONDONTWRITEBYTECODE="1", PYTHONPATH="", GIT_OPTIONAL_LOCKS="0",
                  GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                  PATH="/usr/bin:/bin:/opt/homebrew/bin", UV_OFFLINE="1")
    if fake_git:
        result["PATH"] = fake_git + os.pathsep + result["PATH"]
    return result


def run_cli(source, spec, timeout=90):
    # -S/-P prevent user site packages, editable installs, cwd and PYTHONPATH
    # from choosing a different implementation. Runtime has no dependencies.
    return subprocess.run([sys.executable, "-S", "-P", "-c", BOOTSTRAP,
                           str(Path(source) / "src"), *spec["argv"]],
                          cwd=spec["cwd"], env=environment(spec.get("fake_git")),
                          capture_output=True, timeout=timeout)


def encoded(result):
    return {"exit": result.returncode,
            "stdout": base64.b64encode(result.stdout).decode("ascii"),
            "stderr": base64.b64encode(result.stderr).decode("ascii")}


def differences(expected, actual):
    """Compare original bytes; report first byte offset, including EOF changes."""
    result = {}
    if expected["exit"] != actual["exit"]:
        result["exit"] = [expected["exit"], actual["exit"]]
    for field in ("stdout", "stderr"):
        left, right = (base64.b64decode(item[field], validate=True) for item in (expected, actual))
        if left != right:
            offset = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
            result[field] = {"offset": offset, "lengths": [len(left), len(right)],
                             "sha256": [sha(left), sha(right)]}
    return result


def protected_state(root):
    """HEAD/index/refs/config/worktree bytes and modes; virtual objects/cache allowed.

    Git objects are unreferenced integration products, explicitly outside the
    read-only contract. Capturing every other file also catches new refs, index
    locks, logs, and dirty/untracked-file damage, including bare and linked repos.
    """
    values = {}
    for p in sorted(root.rglob("*")):
        parts = p.relative_to(root).parts
        if "__pycache__" in parts or any(parts[i:i+2] == ("crosswire", "cache") for i in range(len(parts)-1)):
            continue
        if "objects" in parts and (".git" in parts or any(x.endswith(".git") for x in parts)):
            continue
        if p.is_symlink():
            values[p.relative_to(root).as_posix()] = [p.lstat().st_mode, "link", os.readlink(p)]
        elif p.is_file():
            values[p.relative_to(root).as_posix()] = [p.stat().st_mode, sha(p.read_bytes())]
    return values


def restore(artifacts, fixture):
    root = Path(fixture["root"])
    if root.parent != FIXTURE_ROOT or root.is_symlink():
        raise ValueError("Refuse to restore outside the dedicated fixture directory")
    archive = artifacts / fixture["archive"]
    if sha(archive.read_bytes()) != fixture["sha256"]:
        raise ValueError("Fixture archive changed: " + fixture["id"])
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    with tarfile.open(archive) as stream:
        stream.extractall(root, filter="data")
    return root


def cache_files(root):
    return [p for p in sorted(root.rglob("*.json"))
            if any(p.parts[i:i+2] == ("crosswire", "cache") for i in range(len(p.parts)-1))]


def cache_payload(root):
    return {p.relative_to(root).as_posix(): base64.b64encode(p.read_bytes()).decode("ascii")
            for p in cache_files(root)}


def clear_caches(root):
    # Includes bare repositories and linked worktree common directories.
    for p in sorted(root.rglob("crosswire/cache")):
        if p.is_dir():
            shutil.rmtree(p)


def install_cache(root, payload, damage=None):
    clear_caches(root)
    for relative, value in payload.items():
        path = root / relative
        if not path.resolve().is_relative_to(root):
            raise ValueError("Cache path escaped fixture")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(damage if damage is not None else base64.b64decode(value, validate=True))


def branch_orders(fixture):
    result = subprocess.run(["git", "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads"],
                            cwd=fixture["repo"], env=environment(), capture_output=True, check=True)
    labels, seen = [], set()
    for line in result.stdout.decode().splitlines():
        label, commit = line.rsplit(" ", 1)
        if label != "main" and commit not in seen:
            seen.add(commit)
            labels.append(label)
    labels = labels or ["a", "b"]
    orders = [labels]
    if len(labels) > 1:
        orders.append(list(reversed(labels)))
    return orders


def scope_of(invocation):
    """Extract INPUT options, preserving literal roots/repo spelling and cwd.

    This does not parse or normalize any detector output. Original argv is also
    retained unchanged as an observed command, including invalid combinations.
    """
    argv = invocation["argv"]
    if not argv or argv[0] not in {"check", "plan"}:
        return None
    values, branches, flags = defaultdict(list), [], []
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg in {"--repo", "--src", "--target", "--base", "--format"}:
            if index + 1 >= len(argv):
                return None
            values[arg].append(argv[index + 1])
            index += 2
        elif arg.startswith("-"):
            flags.append(arg)
            index += 1
        else:
            branches.append(arg)
            index += 1
    return {"repo": values["--repo"], "roots": values["--src"],
            "target": values["--target"], "base": values["--base"],
            "textual_off": "--no-textual" in flags, "branches": branches,
            "cwd": invocation["cwd"], "fake_git": invocation.get("fake_git")}


def specifications(fixture):
    specs = []
    scopes = {}
    for index, invocation in enumerate(fixture["invocations"]):
        specs.append({**invocation, "id": f"observed-{index}", "kind": "observed", "cache": "cold"})
        scope = scope_of(invocation)
        if scope:
            # Keep every original subset/permutation as an observed invocation.
            # Expand the fullest branch set once per repo/roots/target scope;
            # multiplying every planner prefix by the matrix adds no new scope.
            key = json.dumps({k:v for k,v in scope.items() if k != "branches"}, sort_keys=True)
            if key not in scopes or len(scope["branches"]) > len(scopes[key]["branches"]):
                scopes[key] = scope
    # Direct API-only fixtures still receive the entire CLI matrix.
    if not scopes:
        scope = {"repo": [fixture["repo"]], "roots": [], "target": ["main"], "base": [],
                 "textual_off": False, "branches": branch_orders(fixture)[0],
                 "cwd": fixture["root"], "fake_git": None}
        scopes["default"] = scope
    for scope_index, scope in enumerate(scopes.values()):
        orders = [scope["branches"]]
        if len(scope["branches"]) > 1:
            orders.append(list(reversed(scope["branches"])))
        for order_index, branches in enumerate(orders):
            for mode, formats in FORMATS.items():
                for fmt in formats:
                    for cache in CACHES:
                        argv = ["plan" if mode == "plan" else "check", "--format", fmt]
                        for value in scope["repo"]:
                            argv.extend(["--repo", value])
                        for value in scope["roots"]:
                            argv.extend(["--src", value])
                        targets = scope["target"] or (["main"] if mode != "pairwise" else [])
                        for value in targets:
                            argv.extend(["--target", value])
                        if mode == "pairwise":
                            for value in scope["base"]:
                                argv.extend(["--base", value])
                            if scope["textual_off"]:
                                argv.append("--no-textual")
                        if mode == "combined":
                            argv.append("--combined")
                        if cache == "no-cache":
                            argv.append("--no-cache")
                        specs.append({"id": f"matrix-{scope_index}-{order_index}-{mode}-{fmt}-{cache}",
                                      "kind": "matrix", "mode": mode, "format": fmt,
                                      "order": branches, "cache": cache,
                                      "argv": argv + branches, "cwd": scope["cwd"],
                                      "fake_git": scope["fake_git"]})
    return specs


def record_fixture(artifacts, fixture, baseline, timeout):
    root = restore(artifacts, fixture)
    before = protected_state(root)
    specs = specifications(fixture)
    # This pinned release cache is restored byte-for-byte for BOTH sources.
    seed_specs = [s for s in specs if s["kind"] == "matrix" and s["mode"] == "combined"
                  and s["format"] == "json" and s["cache"] == "cold"]
    rows = []
    clear_caches(root)
    for index, seed_spec in enumerate(seed_specs):
        rows.append({"id": f"seed-{index}", "phase": "seed", "spec": seed_spec,
                     "raw": encoded(run_cli(baseline, seed_spec, timeout))})
    seed = cache_payload(root)
    damage_values = (b"{garbage", b"{}", b"null", b"[]")
    for index, spec in enumerate(specs):
        variant = spec["cache"]
        damage = damage_values[index % 4] if variant == "malformed" else None
        install_cache(root, seed if variant in {"preseeded", "malformed"} else {}, damage)
        if variant == "warm":
            rows.append({"id": spec["id"] + "-warmup", "spec": spec,
                         "raw": encoded(run_cli(baseline, spec, timeout)), "phase": "warmup"})
        rows.append({"id": spec["id"], "spec": spec, "raw": encoded(run_cli(baseline, spec, timeout)),
                     "damage": None if damage is None else base64.b64encode(damage).decode("ascii")})
    if before != protected_state(root):
        raise AssertionError("Baseline changed protected fixture state: " + fixture["id"])
    path = artifacts / "outputs" / (fixture["id"] + ".jsonl.gz")
    path.parent.mkdir(exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    seed_path = artifacts / "outputs" / (fixture["id"] + ".cache.json")
    write_json(seed_path, seed)
    return {"id": fixture["id"], "outputs": str(path.relative_to(artifacts)),
            "outputs_sha256": sha(path.read_bytes()), "seed": str(seed_path.relative_to(artifacts)),
            "seed_sha256": sha(seed_path.read_bytes()), "seed_entries": len(seed), "records": len(rows)}


def replay_fixture(artifacts, fixture, frozen, baseline, candidate, timeout):
    path = artifacts / frozen["outputs"]
    seed_path = artifacts / frozen["seed"]
    if sha(path.read_bytes()) != frozen["outputs_sha256"] or sha(seed_path.read_bytes()) != frozen["seed_sha256"]:
        raise ValueError("Frozen output/cache changed: " + fixture["id"])
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    seed = json.loads(seed_path.read_text())
    mismatches, captured, counts = [], [], Counter()
    for side, checkout in (("baseline", baseline), ("candidate", candidate)):
        root = restore(artifacts, fixture)
        before = protected_state(root)
        for index, row in enumerate(rows):
            spec = row["spec"]
            if row.get("phase") == "seed":
                if index == 0:
                    clear_caches(root)
            elif row.get("phase") == "warmup":
                clear_caches(root)
            elif spec["cache"] != "warm":
                damage = base64.b64decode(row["damage"]) if row.get("damage") else None
                install_cache(root, seed if spec["cache"] in {"preseeded", "malformed"} else {}, damage)
            actual = encoded(run_cli(checkout, spec, timeout))
            delta = differences(row["raw"], actual)
            if delta:
                mismatches.append({"fixture": fixture["id"], "record": row["id"], "side": side, "differences": delta})
            captured.append({"fixture": fixture["id"], "record": row["id"], "side": side, "raw": actual})
            counts[side] += 1
            if side == "candidate":
                counts["cache:" + spec["cache"]] += 1
                counts["kind:" + spec["kind"]] += 1
                counts["exit:" + str(actual["exit"])] += 1
                if "mode" in spec:
                    counts["mode-format:" + spec["mode"] + "/" + spec["format"]] += 1
        if before != protected_state(root):
            raise AssertionError(side + " changed protected fixture state: " + fixture["id"])
    return mismatches, captured, counts


def groups(fixtures):
    grouped = defaultdict(list)
    for fixture in fixtures:
        grouped[fixture["root"]].append(fixture)
    return list(grouped.values())


def parallel_groups(fixtures, action, jobs):
    def run_group(group):
        return [action(fixture) for fixture in group]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_group, group) for group in groups(fixtures)]
        for number, future in enumerate(as_completed(futures), 1):
            yield from future.result()
            if number % 10 == 0:
                print(f"completed fixture groups {number}/{len(futures)}", flush=True)


def release_provenance(baseline):
    tag = subprocess.check_output(["git", "rev-parse", "v0.4.0^{commit}"], cwd=ROOT, env=environment()).decode().strip()
    archive = subprocess.check_output(["git", "archive", "v0.4.0", "src", "tests"], cwd=ROOT, env=environment())
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        expected = {m.name: sha(stream.extractfile(m).read()) for m in stream.getmembers() if m.isfile()}
    expected_source = {k:v for k,v in expected.items() if k.startswith("src/")}
    expected_tests = {k:v for k,v in expected.items() if k.startswith("tests/")}
    actual_tests = {p.relative_to(baseline).as_posix(): sha(p.read_bytes()) for p in sorted((baseline / "tests").rglob("*"))
                    if p.is_file() and "__pycache__" not in p.parts}
    if source_hashes(baseline) != expected_source or actual_tests != expected_tests:
        raise ValueError("--baseline source is not the exact v0.4.0 tag")
    return {"tag": "v0.4.0", "commit": tag, "source_sha256": expected_source}


def compact_harvest(artifacts):
    """Deduplicate INPUT archives that differ only in unreferenced objects/cache.

    Retain the original hashed inventory and union every test ID and literal
    invocation. This operation happens before the first expected byte is saved.
    """
    inventory_path = artifacts / "inventory.json"
    raw = inventory_path.read_bytes()
    inventory = json.loads(raw)
    harvest_path = artifacts / "harvest.json"
    if harvest_path.exists():
        raise ValueError("Input harvest already finalized")
    harvest_path.write_bytes(raw)
    seen, aliases, retained = {}, {}, []
    for fixture in inventory["fixtures"]:
        if sha((artifacts / fixture["archive"]).read_bytes()) != fixture["sha256"]:
            raise ValueError("Harvest archive changed")
        digest = hashlib.sha256()
        with tarfile.open(artifacts / fixture["archive"]) as stream:
            for member in sorted(stream.getmembers(), key=lambda m: m.name):
                parts = Path(member.name).parts
                git = next((i for i,p in enumerate(parts) if p == ".git" or p.endswith(".git")), None)
                if git is not None and any(p in {"objects", "logs", "crosswire"} for p in parts[git+1:]):
                    continue
                digest.update(member.name.encode() + b"\0" + str(member.mode).encode() + b"\0")
                digest.update(member.linkname.encode() + b"\0")
                if member.isfile():
                    digest.update(stream.extractfile(member).read())
        key = (fixture["root"], digest.hexdigest())
        if key not in seen:
            seen[key] = fixture
            retained.append(fixture)
        else:
            prior = seen[key]
            for test in fixture["tests"]:
                if test not in prior["tests"]:
                    prior["tests"].append(test)
            for invocation in fixture["invocations"]:
                if invocation not in prior["invocations"]:
                    prior["invocations"].append(invocation)
        aliases[fixture["id"]] = seen[key]["id"]
    for test in inventory["tests"].values():
        test["fixtures"] = list(dict.fromkeys(aliases[f] for f in test["fixtures"]))
    inventory.update(fixtures=retained, harvest_sha256=sha(raw), harvest_fixture_count=len(aliases))
    write_json(inventory_path, inventory)
    return inventory


def toolchain():
    return {"python_version": sys.version, "python_sha256": sha(Path(sys.executable).resolve().read_bytes()),
            "git_version": subprocess.check_output(["git", "--version"], env=environment()).decode().strip(),
            "git_sha256": sha(Path(shutil.which("git", path=environment()["PATH"])).resolve().read_bytes()),
            "locale": "C", "timezone": "UTC", "pythonhashseed": "0"}


def acquire_lock():
    path = FIXTURE_ROOT.with_name(FIXTURE_ROOT.name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise ValueError("Another comparator owns the fixed fixture namespace") from None
    return handle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS,
                        help="Baseline directory, including an external private location (default: docs/validation/t21-baseline)")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/validation/t21-self-check.json")
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--resume-harvest", action="store_true", help="Finalize complete input harvest only; refuses any existing expectations")
    parser.add_argument("--resume-recording", action="store_true", help="Continue checksummed unfinished recording without replacing completed outputs")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--fixture", action="append", help="Replay selected frozen fixture IDs (partial, cannot pass full gate)")
    args = parser.parse_args(argv)
    baseline, candidate, artifacts = args.baseline.resolve(), args.candidate.resolve(), args.artifacts.resolve()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if (args.resume_harvest or args.resume_recording) and not args.record_baseline:
        parser.error("Resume flags require --record-baseline")
    baseline_hashes, candidate_hashes = source_hashes(baseline), source_hashes(candidate)
    manifest_path = artifacts / "manifest.json"
    started = time.time()
    provenance = release_provenance(baseline)
    harness = {p.name: sha(p.read_bytes()) for p in (Path(__file__), Path(__file__).with_name("t21_capture.py"))}
    namespace_lock = acquire_lock()  # Hold until return/process exit; children do not inherit it.
    if args.record_baseline:
        if args.fixture or (artifacts.exists() and not (args.resume_harvest or args.resume_recording)):
            parser.error("Recording requires a new artifact directory and the complete corpus; never replace expectations")
        if args.resume_recording:
            if manifest_path.exists() or not (artifacts / "recording-checkpoint.json").exists():
                parser.error("Recording resume requires a checkpoint and no final manifest")
        elif args.resume_harvest:
            if manifest_path.exists() or (artifacts / "outputs").exists() or not (artifacts / "inventory.json").exists():
                parser.error("Resume requires a complete harvest with no expected outputs or manifest")
        else:
            if FIXTURE_ROOT.exists():
                parser.error("Dedicated capture directory already exists; move it aside explicitly before recording")
            artifacts.mkdir(parents=True)
            env = environment()
            env["PYTHONPATH"] = str(baseline / "src") + os.pathsep + str(baseline)
            env["CROSSWIRE_GOLDEN_SOURCE"] = str(baseline / "src")
            captured = subprocess.run([sys.executable, str(Path(__file__).with_name("t21_capture.py")),
                                       str(artifacts), str(FIXTURE_ROOT), str(baseline)],
                                      cwd=baseline, env=env, capture_output=True)
            (artifacts / "capture.stdout").write_bytes(captured.stdout)
            (artifacts / "capture.stderr").write_bytes(captured.stderr)
            if captured.returncode:
                raise RuntimeError("Release fixture harvesting failed; inspect capture.stdout/stderr; no baseline accepted")
        context_path = artifacts / "recording-context.json"
        context = {"release": provenance, "toolchain": toolchain(), "capture_sha256": harness["t21_capture.py"]}
        if context_path.exists():
            if json.loads(context_path.read_text()) != context:
                raise ValueError("Recording context/toolchain changed across recovery")
        else:
            with context_path.open("x") as stream:
                json.dump(context, stream, indent=2)
        inventory = json.loads((artifacts / "inventory.json").read_text())
        outcomes = [phase for test in inventory["tests"].values() for phase in test["outcomes"].values()]
        if inventory["exitstatus"] != 0 or any(value != "passed" for value in outcomes) or any(
                set(test["outcomes"]) != {"setup", "call", "teardown"} for test in inventory["tests"].values()):
            raise RuntimeError("A failed/skipped release test cannot silently enter a passing baseline")
        if not args.resume_recording:
            inventory = compact_harvest(artifacts)
        checkpoint_path = artifacts / "recording-checkpoint.json"
        recordings = json.loads(checkpoint_path.read_text())["completed"] if args.resume_recording else []
        for item in recordings:
            if any(sha((artifacts / item[name]).read_bytes()) != item[name + "_sha256"] for name in ("outputs", "seed")):
                raise ValueError("Completed recording changed; will not regenerate")
        completed = {item["id"] for item in recordings}
        # Keep each recorder revision with its own digest. Completed byte files
        # remain untouched across a recovery or recorder scheduling change.
        code_dir = artifacts / "recording-code"
        code_dir.mkdir(exist_ok=True)
        code_path = code_dir / (harness["t21_equality.py"] + ".py")
        if not code_path.exists():
            code_path.write_bytes(Path(__file__).read_bytes())
        pending = [f for f in inventory["fixtures"] if f["id"] not in completed]
        def record_action(fixture):
            output = artifacts / "outputs" / (fixture["id"] + ".jsonl.gz")
            if output.exists():
                raise ValueError("Uncheckpointed output exists; preserve and inspect before recovery")
            item = record_fixture(artifacts, fixture, baseline, args.timeout)
            item["recording_harness_sha256"] = harness["t21_equality.py"]
            return item
        for item in parallel_groups(pending, record_action, args.jobs):
            recordings.append(item)
            temporary_checkpoint = checkpoint_path.with_suffix(".tmp")
            write_json(temporary_checkpoint, {"completed": recordings})
            temporary_checkpoint.replace(checkpoint_path)
        recordings.sort(key=lambda item: item["id"])
        if toolchain() != context["toolchain"] or source_hashes(baseline) != baseline_hashes:
            raise ValueError("Recording source/toolchain changed before freeze")
        manifest = {"version": 1, "release": provenance, "toolchain": toolchain(), "harness_sha256": harness,
                    "recording_context_sha256": sha(context_path.read_bytes()),
                    "inventory_sha256": sha((artifacts / "inventory.json").read_bytes()),
                    "tests_sha256": {p.relative_to(baseline).as_posix(): sha(p.read_bytes()) for p in sorted((baseline / "tests").rglob("*"))
                                     if p.is_file() and "__pycache__" not in p.parts},
                    "recordings": recordings, "test_count": len(inventory["tests"]),
                    "recording_code_sha256": {p.name: sha(p.read_bytes()) for p in sorted(code_dir.glob("*.py"))},
                    "fixture_count": len(inventory["fixtures"]), "record_count": sum(r["records"] for r in recordings)}
        write_json(manifest_path, manifest)
        (artifacts / "manifest.sha256").write_text(sha(manifest_path.read_bytes()) + "  manifest.json\n")
    expected_digest = (artifacts / "manifest.sha256").read_text().split()[0]
    if sha(manifest_path.read_bytes()) != expected_digest:
        raise ValueError("Immutable manifest changed")
    manifest = json.loads(manifest_path.read_text())
    if manifest["release"] != provenance or manifest["toolchain"] != toolchain() or manifest["harness_sha256"] != harness:
        raise ValueError("Release/toolchain/harness drift; do not regenerate expectations")
    if sha((artifacts / "recording-context.json").read_bytes()) != manifest["recording_context_sha256"]:
        raise ValueError("Recording context changed")
    if any(sha((artifacts / "recording-code" / name).read_bytes()) != digest
           for name,digest in manifest["recording_code_sha256"].items()):
        raise ValueError("Archived recorder revision changed")
    inventory_path = artifacts / "inventory.json"
    if sha(inventory_path.read_bytes()) != manifest["inventory_sha256"]:
        raise ValueError("Fixture inventory changed")
    inventory = json.loads(inventory_path.read_text())
    fixtures = inventory["fixtures"]
    if args.fixture:
        fixtures = [f for f in fixtures if f["id"] in args.fixture]
        if {f["id"] for f in fixtures} != set(args.fixture):
            parser.error("Unknown fixture ID")
    recordings = {r["id"]: r for r in manifest["recordings"]}
    mismatches, counts, errors = [], Counter(), []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.output.with_suffix(".outputs.jsonl.gz")
    def action(fixture):
        try:
            return replay_fixture(artifacts, fixture, recordings[fixture["id"]], baseline, candidate, args.timeout)
        except Exception as exc:
            return [{"fixture": fixture["id"], "error": str(exc), "type": type(exc).__name__}], [], Counter(error=1)
    with gzip.open(raw_path, "wt", encoding="utf-8") as raw:
        for delta, observations, totals in parallel_groups(fixtures, action, args.jobs):
            mismatches.extend(delta)
            counts.update(totals)
            for observation in observations:
                raw.write(json.dumps(observation, separators=(",", ":")) + "\n")
    stable = source_hashes(baseline) == baseline_hashes and source_hashes(candidate) == candidate_hashes
    toolchain_stable = toolchain() == manifest["toolchain"]
    status = "fail" if mismatches or not stable or not toolchain_stable else "partial" if args.fixture else "pass"
    report = {"status": status, "manifest_sha256": expected_digest, "release": provenance["commit"],
              "candidate_source_sha256": candidate_hashes, "source_stable": stable,
              "toolchain_stable": toolchain_stable,
              "fixtures": len(fixtures), "tests": manifest["test_count"], "counts": dict(counts),
              "mismatches": mismatches, "raw_sha256": sha(raw_path.read_bytes()),
              "seconds": time.time() - started}
    write_json(args.output, report)
    print(json.dumps({"status": status, "fixtures": len(fixtures), "counts": dict(counts),
                      "mismatches": len(mismatches), "source_stable": stable}), flush=True)
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
