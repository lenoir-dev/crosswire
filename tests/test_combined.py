"""Oracle-based v0.3a acceptance, exercising only public CLI/integration/state APIs.

Fixture edits occupy separated hunks. Native merge-tree assertions distinguish
semantic failures from accidental textual conflicts before checking crosswire.
"""

from dataclasses import FrozenInstanceError
from itertools import combinations, permutations
import json

import pytest


DIRECT = "def f(value):\n    return value\n"
GAP = "".join(f"# Stable separator {i:02d}\n" for i in range(14))
FALLBACK = "try:\n    from fast import f\nexcept ImportError:\n    pass\n"
CALLER = "import m\nm.f(1)\n"


def native_pairs_clean(repo, labels):
    with repo.unchanged():
        for a, b in combinations(labels, 2):
            result = repo.git("merge-tree", "--write-tree", a, b, check=False)
            assert result.returncode == 0, f"Invalid semantic fixture: {a}/{b}: {result.stdout!r}"


def integrate(repo, commits, labels):
    from crosswire.integrate import integrate as public_integrate

    with repo.unchanged():
        return public_integrate(repo.path, commits["target"], [(name, commits[name]) for name in labels])


def resolve(repo, commit, module="m", name="f", roots=(".",)):
    from crosswire.state import StateIndex

    with repo.unchanged():
        return StateIndex(repo.path, commit, roots).resolve(module, name)


def combined(repo, labels, code=None, *options):
    result = repo.check("--target", "main", "--combined", "--format", "json", *options, branches=labels)
    if code is None:
        assert result.returncode in (0, 1), result.stderr
    else:
        assert result.returncode == code, result.stderr
    assert result.stderr == "", result.stderr
    report = json.loads(result.stdout)
    assert report["version"] == 2 and report["mode"] == "combined"
    return report


def semantic(report):
    return [finding for finding in report["findings"] if finding["rule"] in {"CW001", "CW002", "CW006"}]


def assert_break(finding, rule, culprits, branch="C", path="use.py", line=2):
    assert finding["rule"] == rule
    assert finding["severity"] == "error"
    assert finding["branch"] == branch
    assert finding["culprits"] == culprits
    assert finding["culprits_exact"] is True
    assert finding["resolved_by"] is None
    assert (finding["path"], finding["line"], finding["symbol"], finding["location"]) == (
        path, line, "m.f", "integrated",
    )


@pytest.fixture
def conjunctive(repo):
    source = DIRECT + GAP + FALLBACK
    commits = repo.named_dag(
        {"m.py": source, "fast.py": DIRECT},
        {
            "A": ("target", {"m.py": source.replace(DIRECT, "# Direct binding removed\n", 1)}),
            "B": ("target", {"m.py": source.replace(FALLBACK, "# Fallback binding removed\n")}),
            "C": ("target", {"use.py": CALLER}),
        },
    )
    native_pairs_clean(repo, ("A", "B", "C"))
    return commits


@pytest.fixture
def fixed_by_third(repo):
    source = DIRECT + GAP + "# compatibility export slot\n"
    commits = repo.named_dag(
        {"m.py": source, "compat.py": DIRECT},
        {
            "A": ("target", {"m.py": source.replace(DIRECT, "# Direct binding removed\n", 1)}),
            "B": ("target", {"m.py": source + "from compat import f\n"}),
            "C": ("target", {"use.py": CALLER}),
        },
    )
    native_pairs_clean(repo, ("A", "B", "C"))
    return commits


def test_scenario_1_conjunctive_full_set_and_proper_subset_oracle(repo, conjunctive):
    # An explicit state oracle, independent of the detector and its symbol extractor.
    oracle = {
        (): "valid", ("A",): "valid", ("B",): "valid", ("C",): "valid",
        ("A", "B"): "broken", ("A", "C"): "valid", ("B", "C"): "valid",
        ("A", "B", "C"): "broken",
    }
    for subset, expected in oracle.items():
        state = integrate(repo, conjunctive, subset)
        assert state.integrated == subset and state.skipped == ()
        assert resolve(repo, state.commit).status == expected
        if len(subset) >= 2:
            report = combined(repo, subset, 1 if len(subset) == 3 else 0)
            if len(subset) < 3:
                assert report["findings"] == []
    report = combined(repo, ("A", "B", "C"), 1)
    assert len(report["findings"]) == 1
    assert_break(report["findings"][0], "CW006", ["A", "B"])
    assert "no single branch causes it" in report["findings"][0]["message"]
    pairwise = repo.check("--target", "main", "--format", "json", branches=("A", "B", "C"))
    assert pairwise.returncode == 0, pairwise.stderr
    assert json.loads(pairwise.stdout)["findings"] == []


def test_scenario_2_compatibility_third_branch_resolves_pairwise_error(repo, fixed_by_third):
    report = combined(repo, ("A", "B", "C"), 0)
    hits = semantic(report)
    assert len(hits) == 1
    hit = hits[0]
    assert (hit["rule"], hit["severity"], hit["branch"]) == ("CW001", "warning", "C")
    assert hit["culprits"] == ["A"] and hit["culprits_exact"] is True
    assert hit["resolved_by"] == ["B"]
    assert report["summary"] == {"errors": 0, "warnings": 1}
    pairwise = repo.check("--target", "main", "--format", "json", branches=("A", "B", "C"))
    assert pairwise.returncode == 1
    assert any(f["rule"] == "CW001" and f["severity"] == "error" for f in json.loads(pairwise.stdout)["findings"])
    for labels, status, code in [(('A', 'C'), "broken", 1), (('B', 'C'), "valid", 0)]:
        state = integrate(repo, fixed_by_third, labels)
        assert resolve(repo, state.commit).status == status
        combined(repo, labels, code)


def test_scenario_3_single_rename_culprit(repo):
    commits = repo.named_dag(
        {"m.py": DIRECT},
        {"A": ("target", {"m.py": DIRECT.replace("f(", "create_f(")}),
         "C": ("target", {"use.py": CALLER})},
    )
    native_pairs_clean(repo, ("A", "C"))
    assert resolve(repo, commits["C"]).status == "valid"
    report = combined(repo, ("A", "C"), 1)
    assert len(report["findings"]) == 1
    assert_break(report["findings"][0], "CW001", ["A"])


def test_scenario_6_conflicting_branch_is_skipped_and_later_branch_continues(repo):
    commits = repo.named_dag(
        {"m.py": DIRECT, "conflict.txt": "base\n"},
        {
            "A": ("target", {"conflict.txt": "left\n"}),
            "B": ("target", {"conflict.txt": "right\n", "m.py": "# Deleted only on skipped B\n"}),
            "C": ("target", {"use.py": CALLER}),
        },
    )
    state = integrate(repo, commits, ("A", "B", "C"))
    assert state.integrated == ("A", "C")
    assert state.skipped == (("B", ("conflict.txt",)),)
    assert resolve(repo, state.commit).status == "valid"
    assert repo.git("show", f"{state.commit}:m.py").stdout.decode() == DIRECT
    report = combined(repo, ("A", "B", "C"), 1)
    assert report["integrated"] == ["A", "C"]
    assert report["skipped"] == [{"branch": "B", "paths": ["conflict.txt"]}]
    assert semantic(report) == []
    assert len(report["findings"]) == 1
    hit = report["findings"][0]
    assert (hit["rule"], hit["branch"], hit["path"], hit["line"]) == ("CW005", "B", "conflict.txt", 1)
    assert hit["culprits"] == ["A"]
    assert hit["message"] == "textual conflict with A"


@pytest.mark.parametrize("fixture_name", ["conjunctive", "fixed_by_third"])
def test_scenario_8_permutations_preserve_findings_and_read_only_state(repo, request, fixture_name):
    request.getfixturevalue(fixture_name)
    repo.write("dirty.txt", "staged\n")
    repo.git("add", "dirty.txt")
    repo.write("dirty.txt", "unstaged\n")
    repo.write("untracked.txt", "retain this\n")
    expected = None
    for order in permutations(("A", "B", "C")):
        report = combined(repo, order)
        assert report["integrated"] == list(order) and report["skipped"] == []
        if expected is None:
            expected = report["findings"]
            assert expected
        assert report["findings"] == expected, "PLAN-v0.3a §5.8: order changes findings for a clean merge set"


def test_combined_json_v2_exact_shape_and_deterministic_serialization(repo, conjunctive):
    first = repo.check("--target", "main", "--combined", "--format", "json", branches=("A", "B", "C"))
    second = repo.check("--target", "main", "--combined", "--format", "json", branches=("A", "B", "C"))
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout and first.stderr == second.stderr == ""
    report = json.loads(first.stdout)
    assert set(report) == {"version", "tool", "mode", "target", "integrated", "skipped", "findings", "summary", "coverage", "limits"}
    assert report["coverage"] == "complete" and report["limits"]["hit"] == []
    assert report["version"] == 2 and report["tool"] == "crosswire" and report["mode"] == "combined"
    assert report["target"] == conjunctive["target"]
    assert report["integrated"] == ["A", "B", "C"] and report["skipped"] == []
    assert report["summary"] == {"errors": 1, "warnings": 0}
    assert set(report["findings"][0]) == {
        "rule", "severity", "message", "branch", "culprits", "culprits_exact", "resolved_by",
        "path", "line", "location", "symbol",
    }
    assert first.stdout.rstrip("\n") == json.dumps(report, sort_keys=True, indent=2)


@pytest.mark.parametrize("options", [[], ["--target", "main", "--no-textual"]])
def test_combined_cli_invalid_option_combinations(repo, options):
    repo.pair({}, {"a.txt": "a\n"}, {"b.txt": "b\n"})
    result = repo.check("--combined", *options)
    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr.startswith("crosswire: error:")


def test_integration_is_deterministic_independent_of_identity_and_signing(repo, monkeypatch):
    from crosswire.integrate import integrate as public_integrate

    commits = repo.named_dag({}, {"A": ("target", {"a.txt": "a\n"}), "B": ("target", {"b.txt": "b\n"})})
    # A configured signing key must never be used for virtual commits.
    repo.git("config", "commit.gpgSign", "true")
    repo.git("config", "user.signingkey", "nonexistent-crosswire-test-key")
    for name, value in {
        "GIT_AUTHOR_NAME": "Hostile author", "GIT_COMMITTER_NAME": "Hostile committer",
        "GIT_AUTHOR_EMAIL": "hostile@example.invalid", "GIT_COMMITTER_EMAIL": "hostile@example.invalid",
        "GIT_AUTHOR_DATE": "2030-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2030-01-01T00:00:00+0000",
    }.items():
        monkeypatch.setenv(name, value)
    state = integrate(repo, commits, ("A", "B"))
    assert len(state.commit) in (40, 64)
    raw = repo.git("cat-file", "commit", state.commit).stdout.decode()
    assert "author crosswire <crosswire@invalid> 0 +0000\n" in raw
    assert "committer crosswire <crosswire@invalid> 0 +0000\n" in raw
    assert raw.endswith("\ncrosswire virtual merge\n")
    parents = [line.removeprefix("parent ") for line in raw.splitlines() if line.startswith("parent ")]
    assert len(parents) == 2 and parents[1] == commits["B"]
    expected_parent = integrate(repo, commits, ("A",)).commit
    assert parents[0] == expected_parent
    assert integrate(repo, commits, ("A", "B")).commit == state.commit
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Another author")
    with repo.unchanged():
        # New labels and repo path spelling still describe exactly the same object graph.
        repeated = public_integrate(repo.path / ".", commits["target"], [("x", commits["A"]), ("y", commits["B"])])
    assert repeated.commit == state.commit and repeated.integrated == ("x", "y")
    assert not hasattr(state, "__dict__")
    with pytest.raises(FrozenInstanceError):
        state.commit = commits["target"]


def test_integration_empty_and_all_conflicted_inputs_preserve_target(repo):
    commits = repo.named_dag(
        {"conflict.txt": "base\n"},
        {"A": ("target", {"conflict.txt": "left\n"}), "B": ("target", {"conflict.txt": "right\n"})},
    )
    empty = integrate(repo, commits, ())
    assert (empty.commit, empty.integrated, empty.skipped) == (commits["target"], (), ())
    # Integrate against A as target: B must be skipped without creating a commit.
    alternate = {**commits, "target": commits["A"]}
    skipped = integrate(repo, alternate, ("B",))
    assert skipped.commit == commits["A"] and skipped.integrated == ()
    assert skipped.skipped == (("B", ("conflict.txt",)),)


@pytest.mark.parametrize(("old", "new", "call", "broken"), [
    ("value", "value, required", "m.f(1)", True),
    ("value", "value, *, required", "m.f(1)", True),
    ("value, optional=0", "value", "m.f(1, optional=2)", True),
    ("value", "value, optional=0", "m.f(1)", False),
    ("value", "value, required", "m.f(*args)", False),
    ("value", "value, required", "m.f(1, **kwargs)", False),
    ("value", "value, required", "m.f()", False),  # broken at the caller's tip
])
def test_scenario_4_call_binding_oracle(repo, old, new, call, broken):
    repo.named_dag(
        {"m.py": f"def f({old}): pass\n"},
        {"A": ("target", {"m.py": f"def f({new}): pass\n"}),
         "C": ("target", {"use.py": "import m\n" + call + "\n"})},
    )
    native_pairs_clean(repo, ("A", "C"))
    report = combined(repo, ("A", "C"), 1 if broken else 0)
    if broken:
        assert len(report["findings"]) == 1
        assert_break(report["findings"][0], "CW002", ["A"])
    else:
        assert report["findings"] == []


def test_scenario_5_conjunctive_culprits_exclude_same_file_decoy(repo, conjunctive):
    base_source = DIRECT + GAP + FALLBACK
    repo.branch("D", conjunctive["target"])
    repo.checkout("D")
    # D changes the target file and is a candidate, but cannot affect resolution.
    repo.write("m.py", base_source.replace("# Stable separator 07", "# Harmless decoy change"))
    repo.commit("decoy")
    native_pairs_clean(repo, ("A", "B", "C", "D"))
    for order in [("D", "A", "B", "C"), ("C", "B", "A", "D")]:
        report = combined(repo, order, 1)
        assert len(report["findings"]) == 1
        assert_break(report["findings"][0], "CW006", ["A", "B"])


def test_scenario_5_competing_fixes_choose_lexical_minimum_independent_of_order(repo):
    source = DIRECT + GAP + "# B export slot\n" + GAP + "# D export slot\n"
    repo.named_dag(
        {"m.py": source, "compat.py": DIRECT},
        {
            "A": ("target", {"m.py": source.replace(DIRECT, "# Removed direct binding\n", 1)}),
            "B": ("target", {"m.py": source.replace("# B export slot\n", "# B export slot\nfrom compat import f\n")}),
            "C": ("target", {"use.py": CALLER}),
            "D": ("target", {"m.py": source.replace("# D export slot\n", "# D export slot\nfrom compat import f\n"),
                             "unrelated.txt": "decoy\n"}),
        },
    )
    native_pairs_clean(repo, ("A", "B", "C", "D"))
    expected = None
    for order in [("A", "B", "C", "D"), ("D", "C", "B", "A"), ("C", "A", "D", "B")]:
        report = combined(repo, order, 0)
        assert len(report["findings"]) == 1
        hit = report["findings"][0]
        assert (hit["rule"], hit["severity"], hit["branch"]) == ("CW001", "warning", "C")
        assert hit["culprits"] == ["A"] and hit["culprits_exact"] is True
        assert hit["resolved_by"] == ["B"]
        if expected is None:
            expected = report["findings"]
        assert report["findings"] == expected


def test_scenario_7_preexisting_missing_names_and_third_party_are_not_blameable(repo):
    repo.named_dag(
        {"m.py": DIRECT},
        {
            "A": ("target", {"m.py": "# All API removed\n"}),
            "C": ("target", {"use.py": "import m\nimport external_uninstalled_package\nm.never_existed(1)\nexternal_uninstalled_package.f()\n"}),
        },
    )
    native_pairs_clean(repo, ("A", "C"))
    report = combined(repo, ("A", "C"), 0)
    assert report["findings"] == []


@pytest.mark.parametrize(("files", "module", "name", "expected", "consulted"), [
    ({"m.py": DIRECT}, "m", "f", "valid", {"m.py"}),
    ({"m.py": "value: int = 1\n"}, "m", "value", "valid", {"m.py"}),
    ({"m.py": "import external as exported\n"}, "m", "exported", "valid", {"m.py"}),
    ({"m.py": "if enabled:\n    def f(x): pass\nelse:\n    def f(x, y): pass\n"}, "m", "f", "valid", {"m.py"}),
    ({"m.py": "try:\n    value = 1\nexcept ImportError:\n    value = 2\n"}, "m", "value", "valid", {"m.py"}),
    ({"m.py": "# No f\n"}, "m", "f", "broken", {"m.py"}),
    ({"m.py": "from impl import *\n", "impl.py": DIRECT}, "m", "f", "broken", {"m.py"}),
    ({"m.py": "def broken(\n"}, "m", "f", "unknown", {"m.py"}),
    ({"unrelated.py": ""}, "external_uninstalled_package", "f", "unknown", set()),
    ({"m.py": "from impl import f\n", "impl.py": "# No f\n"}, "m", "f", "broken", {"m.py", "impl.py"}),
    ({"m.py": "from impl import f\n", "impl.py": "def broken(\n"}, "m", "f", "unknown", {"m.py", "impl.py"}),
])
def test_state_resolution_oracle(repo, files, module, name, expected, consulted):
    repo.apply(files)
    commit = repo.commit("state oracle")
    result = resolve(repo, commit, module, name)
    assert result.status == expected
    assert isinstance(result.files, tuple)
    assert consulted <= set(result.files)
    assert all(not path.startswith("/") for path in result.files)
    if expected != "valid":
        assert result.symbol is None
    assert resolve(repo, commit, module, name) == result
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.status = "broken"


def test_state_follows_aliased_relative_reexport_chain_and_preserves_signature(repo):
    repo.apply({
        "pkg/__init__.py": "from .facade import exported as f\n",
        "pkg/facade.py": "from .impl import original as exported\n",
        "pkg/impl.py": "def original(value, *, limit=1): return value\n",
    })
    commit = repo.commit("reexport chain")
    result = resolve(repo, commit, "pkg", "f")
    assert result.status == "valid" and result.symbol is not None
    assert result.symbol.qualname == "original"
    assert [(p.name, p.kind, p.has_default) for p in result.symbol.params] == [
        ("value", "pos", False), ("limit", "kwonly", True),
    ]
    assert set(result.files) == {"pkg/__init__.py", "pkg/facade.py", "pkg/impl.py"}


def test_state_reexport_cycle_and_depth_limit_are_unknown(repo):
    repo.apply({"m.py": "from loop import f\n", "loop.py": "from m import f\n"})
    for i in range(8):
        repo.write(f"chain{i}.py", f"from chain{i + 1} import f\n" if i < 7 else DIRECT)
    commit = repo.commit("cycle and long chain")
    assert resolve(repo, commit).status == "unknown"
    assert resolve(repo, commit, "chain0", "f").status == "unknown"


def test_state_source_root_priority(repo):
    repo.apply({"src/m.py": DIRECT, "m.py": "# no f at repo root\n"})
    commit = repo.commit("roots")
    assert resolve(repo, commit, roots=("src", ".")).status == "valid"
    assert resolve(repo, commit, roots=(".", "src")).status == "broken"


def test_combined_reexport_dependency_is_a_culprit_file(repo):
    repo.named_dag(
        {"m.py": "from impl import f\n", "impl.py": DIRECT},
        {"A": ("target", {"impl.py": "# Removed implementation\n"}),
         "C": ("target", {"use.py": CALLER})},
    )
    report = combined(repo, ("A", "C"), 1)
    assert len(report["findings"]) == 2
    findings = {(hit["branch"], hit["path"], hit["symbol"]): hit for hit in report["findings"]}
    assert set(findings) == {("C", "use.py", "m.f"), ("main", "m.py", "impl.f")}
    assert_break(findings[("C", "use.py", "m.f")], "CW001", ["A"])
    target = findings[("main", "m.py", "impl.f")]
    assert target["rule"] == "CW001" and target["severity"] == "error"
    assert target["culprits"] == ["A"] and target["culprits_exact"] is True
    assert target["resolved_by"] is None
    assert target["line"] == 1 and target["location"] == "integrated"


def test_combined_deleted_repo_module_is_broken_not_third_party(repo):
    repo.named_dag(
        {"m.py": DIRECT},
        {"A": ("target", {"m.py": None}), "C": ("target", {"use.py": CALLER})},
    )
    report = combined(repo, ("A", "C"), 1)
    assert len(report["findings"]) == 1
    assert_break(report["findings"][0], "CW001", ["A"])


def test_combined_location_is_reextracted_after_other_branch_shifts_lines(repo):
    original = "import m\n" + GAP + "# Call additions below\n"
    header = "# New module header\n# Added independently\n# Third header line\n"
    repo.named_dag(
        {"m.py": DIRECT, "use.py": original},
        {"A": ("target", {"m.py": "# Removed f\n", "use.py": header + original}),
         "C": ("target", {"use.py": original + "m.f(1)\n"})},
    )
    native_pairs_clean(repo, ("A", "C"))
    report = combined(repo, ("A", "C"), 1)
    assert len(report["findings"]) == 1
    assert_break(report["findings"][0], "CW001", ["A"], line=len((header + original).splitlines()) + 1)


def test_combined_location_falls_back_to_branch_when_original_path_was_renamed(repo):
    original = "import m\n" + GAP + "# Call additions below\n"
    repo.named_dag(
        {"m.py": DIRECT, "use.py": original},
        {"A": ("target", {"m.py": "# Removed f\n", "use.py": None, "renamed_use.py": original}),
         "C": ("target", {"use.py": original + "m.f(1)\n"})},
    )
    native_pairs_clean(repo, ("A", "C"))
    report = combined(repo, ("A", "C"), 1)
    assert len(report["findings"]) == 1
    hit = report["findings"][0]
    assert (hit["rule"], hit["branch"], hit["culprits"], hit["path"], hit["line"], hit["location"]) == (
        "CW001", "C", ["A"], "use.py", len(original.splitlines()) + 1, "branch",
    )
