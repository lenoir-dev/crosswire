"""Frozen v0.4 T14–T20: public diagnostics, coverage, schemas and odd Git states."""

import importlib.resources
import json
from pathlib import Path
import shlex
import subprocess
import zipfile

import pytest

from .test_combined import DIRECT, FALLBACK, GAP


def build_pair(repo, malformed=None):
    base = {"m.py": DIRECT}
    if malformed:
        base.update(malformed)
    return repo.pair(base, {"m.py": DIRECT.replace("f(", "renamed(")}, {"use.py": "import m\nm.f(1)\n"})


def decode(result, code=1):
    assert result.returncode == code, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["pairwise", "combined", "plan"])
def test_t14_findings_have_hint_and_limitations_in_all_json_modes(repo, mode):
    build_pair(repo)
    if mode == "plan":
        # The added caller makes the pair unsafe; the planner must explain its blocker.
        report = decode(repo.cli("plan", "--repo", str(repo.path), "--target", "main", "--format", "json", "a", "b"))
        findings = [f for entry in report["blocked"] for f in entry["findings"]]
    else:
        options = ["--target", "main", "--combined"] if mode == "combined" else []
        report = decode(repo.check(*options, "--format", "json"))
        findings = report["findings"]
    assert findings
    assert report["coverage"] in {"complete", "bounded", "partial"}
    assert isinstance(report["limitations"], dict)
    for finding in findings:
        assert "hint" in finding and (finding["hint"] is None or isinstance(finding["hint"], str))
        assert isinstance(finding["limitations"], list)
        assert finding["hint"], "A straightforward renamed function has a justified hint"


def test_t14_rename_hint_and_required_keyword_are_actionable(repo):
    build_pair(repo)
    report = decode(repo.check("--format", "json"))
    hit = next(f for f in report["findings"] if f["rule"] == "CW001")
    assert "renamed" in hit["hint"]


def test_t14_missing_required_keyword_hint_names_the_parameter(repo):
    repo.pair({"m.py": DIRECT}, {"m.py": "def f(value, *, template): pass\n"}, {"use.py": "import m\nm.f(1)\n"})
    hit = next(f for f in decode(repo.check("--format", "json"))["findings"] if f["rule"] == "CW002")
    assert "template" in hit["hint"] and "pass" in hit["hint"].lower()


@pytest.mark.parametrize("combined_mode", [False, True])
def test_t14_sarif_findings_expose_hint_and_limitations(repo, combined_mode):
    build_pair(repo)
    options = ["--target", "main", "--combined"] if combined_mode else []
    data = decode(repo.check(*options, "--format", "sarif"))
    properties = data["runs"][0]["results"][0]["properties"]
    assert isinstance(properties["hint"], str)
    assert isinstance(properties["limitations"], list)
    if combined_mode:
        assert "repro" in properties


def test_t15_repro_is_shell_quoted_minimal_and_respects_target_and_roots(repo):
    repo.named_dag({"lib source/m.py": DIRECT}, {
        "remove'api": ("target", {"lib source/m.py": "# removed\n"}),
        "use%api": ("target", {"consumer sources/use.py": "import m\nm.f(1)\n"}),
        "decoy": ("target", {"decoy.txt": "safe\n"}),
    })
    repo.branch("release'candidate", "main")
    result = repo.check("--target", "release'candidate", "--src", "lib source", "--src", "consumer sources", "--combined", "--format", "json",
                        branches=("remove'api", "decoy", "use%api"))
    report = decode(result)
    hit = next(f for f in report["findings"] if f["rule"] == "CW001")
    assert hit["culprits_exact"] is True and isinstance(hit["repro"], str)
    args = shlex.split(hit["repro"])
    assert args[:2] == ["crosswire", "check"]
    assert "--combined" in args and "--target" in args
    assert args[args.index("--target") + 1] in {"release'candidate", report["target"]}
    assert [args[i + 1] for i, value in enumerate(args) if value == "--src"] == ["lib source", "consumer sources"]
    assert "remove'api" in args and "use%api" in args and "decoy" not in args
    if "--format" not in args:
        args.extend(["--format", "json"])
    if "--repo" not in args:
        args.extend(["--repo", str(repo.path)])
    reproduced = decode(repo.cli(*args[1:], cwd=repo.path))
    assert any(f["rule"] == hit["rule"] and f["symbol"] == hit["symbol"] for f in reproduced["findings"])


def test_t14_t15_combined_break_hint_and_minimal_three_branch_repro(repo):
    source = DIRECT + GAP + FALLBACK
    repo.named_dag({"m.py": source, "fast.py": DIRECT}, {
        "A": ("target", {"m.py": source.replace(DIRECT, "# removed direct binding\n", 1)}),
        "B": ("target", {"m.py": source.replace(FALLBACK, "# removed fallback\n")}),
        "C": ("target", {"use.py": "import m\nm.f(1)\n"}),
        "D": ("target", {"safe.txt": "decoy\n"}),
    })
    report = decode(repo.check("--target", "main", "--combined", "--format", "json", branches=("D", "C", "B", "A")))
    finding = next(f for f in report["findings"] if f["rule"] == "CW006")
    assert "compatibility shim" in finding["hint"]
    assert "A" in finding["hint"] and "B" in finding["hint"]
    args = shlex.split(finding["repro"])
    assert all(branch in args for branch in ("A", "B", "C")) and "D" not in args
    args.extend(["--repo", str(repo.path), "--format", "json"])
    reproduced = decode(repo.cli(*args[1:], cwd=repo.path))
    assert any(f["rule"] == "CW006" and f["culprits"] == ["A", "B"] for f in reproduced["findings"])


@pytest.mark.parametrize("rule", ["CW003", "CW004", "CW005"])
def test_t14_duplicate_migration_and_textual_hints_are_justified(repo, rule):
    if rule == "CW003":
        repo.pair({}, {"m.py": "def f(): return 1\n"}, {"m.py": "def f(): return 2\n"})
        options, code = ["--no-textual"], 0
    elif rule == "CW004":
        repo.pair({}, {"app/migrations/0007_a.py": ""}, {"app/migrations/0007_b.py": ""})
        options, code = [], 1
    else:
        repo.pair({"x.txt": "base\n"}, {"x.txt": "a\n"}, {"x.txt": "b\n"})
        options, code = [], 1
    hit = next(f for f in decode(repo.check(*options, "--format", "json"), code)["findings"] if f["rule"] == rule)
    assert isinstance(hit["hint"], str)
    if rule == "CW003":
        assert hit["hint"] == "keep one definition"
    elif rule == "CW004":
        assert "renumber" in hit["hint"] and "0008" in hit["hint"]
    else:
        assert hit["hint"] == "rebase b onto a"


@pytest.mark.parametrize("version,mode", [(1, "check"), (2, "check"), (2, "plan")])
def test_t17_schema_is_offline_valid_and_shipped_as_package_data(repo, version, mode):
    import jsonschema

    result = repo.cli("schema", "--version", str(version), "--mode", mode)
    schema = decode(result, 0)
    assert schema["$schema"].rstrip("#") == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)
    name = "plan-v2.schema.json" if mode == "plan" else f"report-v{version}.schema.json"
    packaged = importlib.resources.files("crosswire").joinpath("schemas", name).read_text()
    assert schema == json.loads(packaged)
    assert result.stderr == ""


def test_t17_built_wheel_contains_all_three_json_schemas(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    wheel = next(tmp_path.glob("crosswire-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for name in ("report-v1", "report-v2", "plan-v2"):
            path = f"crosswire/schemas/{name}.schema.json"
            assert path in names
            assert json.loads(archive.read(path))["$schema"].rstrip("#") == "https://json-schema.org/draft/2020-12/schema"


def test_t17_validates_every_legacy_json_golden_without_dropping_fields(repo):
    import jsonschema

    schema = decode(repo.cli("schema", "--version", "1"), 0)
    golden = json.loads((Path(__file__).parent / "golden/v01.json").read_text())["cases"]
    count = 0
    for key, payload in golden.items():
        if "::cli::" in key and payload["stdout"].lstrip().startswith("{"):
            jsonschema.validate(json.loads(payload["stdout"]), schema)
            count += 1
    assert count >= 50


@pytest.mark.parametrize("mode", ["pairwise", "combined", "plan"])
def test_t17_current_outputs_validate_against_their_schema(repo, mode):
    import jsonschema

    build_pair(repo)
    if mode == "plan":
        result = repo.cli("plan", "--repo", str(repo.path), "--target", "main", "--format", "json", "a", "b")
    else:
        options = ["--target", "main", "--combined"] if mode == "combined" else []
        result = repo.check(*options, "--format", "json")
    report = decode(result)
    schema = decode(repo.cli("schema", "--version", str(report["version"]), "--mode", "plan" if mode == "plan" else "check"), 0)
    jsonschema.validate(report, schema)


@pytest.mark.parametrize("kind", ["parse", "huge", "splatted"])
def test_t16_partial_coverage_has_bounded_deterministic_examples_and_no_exit_change(repo, kind):
    if kind == "parse":
        files = {f"bad{i}.py": "def bad(\n" for i in range(8)}
    elif kind == "huge":
        files = {"huge.py": "#" + "x" * (2 * 1024 * 1024 + 1)}
    else:
        files = {"splatted.py": "import m\ndef use(args):\n    m.f(*args)\n"}
    repo.pair({"m.py": DIRECT}, {"a.txt": "safe\n"}, {"b.txt": "safe\n", **files})
    first = repo.check("--format", "json")
    second = repo.check("--format", "json")
    report = decode(first, 0)
    assert report["coverage"] == "partial"
    assert first.stdout == second.stdout
    assert isinstance(report["limitations"], dict) and report["limitations"]
    categories = [value for value in report["limitations"].values() if isinstance(value, dict) and "count" in value]
    assert categories
    assert sum(value["count"] for value in categories) == (8 if kind == "parse" else 1)
    for category in categories:
        assert len(category["examples"]) <= 5
        assert len(category["examples"]) == len(set(map(str, category["examples"])))


def test_t18_detached_head_and_bare_repositories_are_supported(repo, tmp_path):
    build_pair(repo)
    repo.git("checkout", "--detach", "a")
    assert repo.check("--format", "json").returncode == 1
    bare = tmp_path / "bare.git"
    repo.git("clone", "--bare", str(repo.path), str(bare))
    before = subprocess.check_output(["git", "--git-dir", str(bare), "for-each-ref"])
    result = repo.cli("check", "--repo", str(bare), "--format", "json", "a", "b")
    assert result.returncode == 1, result.stderr
    assert subprocess.check_output(["git", "--git-dir", str(bare), "for-each-ref"]) == before


def test_t18_unborn_and_shallow_repositories_have_clear_errors(repo, tmp_path):
    unborn = tmp_path / "unborn"
    repo.git("init", "-b", "main", str(unborn))
    result = repo.cli("check", "--repo", str(unborn), "a", "b")
    assert result.returncode == 2 and result.stdout == ""
    assert any(word in result.stderr.lower() for word in ("unborn", "no commit", "empty"))
    build_pair(repo)
    shallow = tmp_path / "shallow"
    repo.git("clone", "--depth", "1", "--no-single-branch", repo.path.as_uri(), str(shallow))
    result = repo.cli("check", "--repo", str(shallow), "origin/a", "origin/b")
    assert result.returncode == 2 and result.stdout == ""
    assert "shallow" in result.stderr.lower()


def test_t18_non_utf8_source_never_crashes(repo):
    repo.pair({"m.py": DIRECT}, {"a.txt": "safe\n"}, {"bad.py": b"# undecodable: \xff\nvalue = 1\n"})
    result = repo.check("--format", "json")
    report = decode(result, 0)
    assert report["coverage"] in {"complete", "partial"}


def test_t18_submodule_is_ignored_and_reported_without_initializing_it(repo, tmp_path):
    other = tmp_path / "submodule-source"
    other.mkdir()
    repo.git("init", "-b", "main", str(other))
    (other / "broken.py").write_text("def broken(\n")
    subprocess.run(["git", "add", "."], cwd=other, env=repo.env, capture_output=True, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "-m", "submodule"], cwd=other, env=repo.env, capture_output=True, check=True)
    repo.pair({}, {"a.txt": "a\n"}, {"b.txt": "b\n"})
    repo.git("-c", "protocol.file.allow=always", "submodule", "add", str(other), "vendor")
    repo.commit("requested branch adds submodule")
    result = repo.check("--format", "json")
    report = decode(result, 0)
    assert report["coverage"] == "partial"
    assert "submodule" in json.dumps(report["limitations"]).lower()
    assert "vendor/broken.py" not in result.stderr


def test_t16_bounded_wins_over_partial_and_inexact_repro_is_null(repo):
    source = "".join(f"value_{i} = 0\n" + GAP for i in range(7))
    changes = {f"A{i}": ("target", {"same.py": source.replace(f"value_{i} = 0", f"value_{i} = 1")}) for i in range(7)}
    changes["X"] = ("target", {"same.py": source.replace("value_0 = 0", "value_0 = 2"), "unparsable.py": "def broken(\n"})
    repo.named_dag({"same.py": source}, changes)
    report = decode(repo.check("--target", "main", "--combined", "--format", "json", branches=tuple(changes)))
    assert report["coverage"] == "bounded" and report["limits"]["hit"]
    assert report["limitations"]
    assert any(f["culprits_exact"] is False and f["repro"] is None for f in report["findings"])


def test_t16_unknown_resolution_is_visible_once_not_per_internal_trial(repo):
    repo.named_dag({"m.py": DIRECT, "opaque.py": "def __getattr__(name): return 1\n"}, {
        "A": ("target", {"a.txt": "safe\n"}),
        "B": ("target", {"b.txt": "safe\n"}),
        "C": ("target", {"use.py": "import opaque\nopaque.run()\n"}),
    })
    report = decode(repo.check("--target", "main", "--combined", "--format", "json", branches=("A", "B", "C")), 0)
    assert report["coverage"] == "partial"
    category = next(value for key, value in report["limitations"].items() if "unknown" in key)
    assert category["count"] == 1 and len(category["examples"]) == 1


def test_t16_unsupported_constructs_have_distinct_site_counts(repo):
    source = "from external import *\n@decorate\ndef f(): pass\ngetattr(object(), 'name')\n"
    repo.pair({}, {"a.txt": "safe\n"}, {"unsupported.py": source})
    report = decode(repo.check("--format", "json"), 0)
    assert report["coverage"] == "partial"
    unsupported = next(value for key, value in report["limitations"].items() if "unsupported" in key)
    assert unsupported["count"] == 3


def test_t20_target_conflict_is_not_falsely_explained_as_order_dependent(repo):
    repo.named_dag({"conflict.txt": "base\n"}, {"U": ("target", {"conflict.txt": "feature\n"}), "S": ("target", {"safe.txt": "safe\n"})})
    repo.checkout("main")
    repo.write("conflict.txt", "target changed\n")
    repo.commit("advance target")
    result = repo.cli("plan", "--repo", str(repo.path), "--target", "main", "--format", "json", "U", "S")
    report = decode(result)
    assert report["steps"][0]["branches"] == ["S"]
    reason = report["steps"][0]["reason"]
    assert "placed before U" not in reason and "resolves" not in reason
    assert report["blocked"][0]["branch"] == "U"
