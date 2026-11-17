"""Frozen PLAN-v0.2 §12.1–12.5: public regression and feature contracts."""

from dataclasses import FrozenInstanceError
from itertools import permutations
import json
from pathlib import Path
import re

import pytest

from .golden_support import baseline


def build_stale(repo):
    return repo.pair(
        {"api.py": "def f(x): return x\n"},
        {"api.py": "def renamed(x): return x\n"},
        {"client.py": "import api\napi.f(1)\n"},
    )


def payload(result, code=None):
    if code is None:
        assert result.returncode in (0, 1), result.stderr
    else:
        assert result.returncode == code, result.stderr
    return json.loads(result.stdout)


def cache_dir(repo):
    common = Path(repo.git("rev-parse", "--git-common-dir").stdout.decode().strip())
    return (common if common.is_absolute() else repo.path / common) / "crosswire/cache/v1"


def test_v01_golden_provenance_and_scenario_coverage():
    golden = baseline()
    assert golden["provenance"]["commit"] == "562deeb"
    cases = golden["cases"]
    assert len(cases) >= 100
    assert any("test_cw001_demo" in key and "::analyze::" in key for key in cases)
    for rule in ("cw001", "cw002", "cw003", "cw004", "cw005"):
        assert any(rule in key and "::cli::" in key for key in cases)
    assert any("test_readme_demo_cli" in key for key in cases)


def test_summary_public_contract(repo):
    from crosswire.engine import summarize
    from crosswire.model import BranchSummary

    base = build_stale(repo)
    tip = repo.git("rev-parse", "a").stdout.decode().strip()
    with repo.unchanged():
        summary = summarize(repo.path, "a", tip, base, (".",))
    assert isinstance(summary, BranchSummary)
    assert (summary.label, summary.tip, summary.base, summary.roots) == ("a", tip, base, (".",))
    assert isinstance(summary.changes, tuple)
    assert isinstance(summary.references, tuple)
    assert isinstance(summary.touched_modules, frozenset)
    assert isinstance(summary.referenced_modules, frozenset)
    assert "api" in summary.touched_modules
    assert summary.referenced_modules == frozenset()
    assert summary.api["api"][0].qualname == "f"
    assert isinstance(summary.api["api"], tuple)
    assert "renamed" in summary.definitions["api"]
    assert isinstance(summary.redefined, frozenset)
    assert isinstance(summary.migrations, dict)
    assert not hasattr(summary, "__dict__")
    with pytest.raises(FrozenInstanceError):
        summary.label = "other"


def test_engine_summarizes_each_branch_once_for_shared_base(repo, monkeypatch):
    from crosswire import git

    base = build_stale(repo)
    repo.branch("c", base)
    repo.checkout("c")
    repo.write("independent.txt", "c\n")
    repo.commit("third")
    calls = []
    original = git.changed_files

    def counted(repo, base, tip):
        calls.append((tip, base))
        return original(repo, base, tip)

    monkeypatch.setattr(git, "changed_files", counted)
    repo.analyze(("a", "b", "c"), textual=False)
    assert len(calls) == len(set(calls)) == 3


@pytest.mark.parametrize("scenario", ["semantic", "textual", "migrations", "definitions"])
def test_branch_order_invariance_of_findings(repo, scenario):
    if scenario == "semantic":
        base = build_stale(repo)
    elif scenario == "textual":
        base = repo.pair({"a.txt": "base\n"}, {"a.txt": "left\n"}, {"a.txt": "right\n"})
    elif scenario == "migrations":
        base = repo.pair({}, {"app/migrations/0007_a.py": "# a\n"}, {"app/migrations/0007_b.py": "# b\n"})
    else:
        base = repo.pair({}, {"api.py": "def f(): return 1\n"}, {"api.py": "def f(): return 2\n"})
    repo.branch("c", base)
    repo.checkout("c")
    repo.write("independent.txt", "unrelated\n")
    repo.commit("independent")
    expected = None
    for branches in permutations(("a", "b", "c")):
        report = payload(repo.check("--format", "json", branches=branches))
        assert len(report["pairs"]) == 3
        if expected is None:
            expected = report["findings"]
            assert expected
        assert report["findings"] == expected, "PLAN-v0.2 §12.5 requires invariant finding sets"


def test_target_uses_individual_merge_bases_and_preserves_pair_base(repo):
    # Target has already removed f. Branch a's own base contains f, while b's does not.
    repo.write("api.py", "def f(x): return x\n")
    original = repo.commit("original")
    repo.branch("a", original)
    repo.write("api.py", "# removed on target\n")
    target = repo.commit("target removal")
    repo.branch("b", target)
    repo.checkout("a")
    repo.write("api.py", "# independently removed on a\n")
    repo.commit("a removal")
    repo.checkout("b")
    repo.write("client.py", "import api\napi.f(1)\n")
    repo.commit("b call")
    result = payload(repo.check("--target", "main", "--no-textual", "--format", "json"), 1)
    assert result["pairs"] == [{"a": "a", "b": "b", "base": original}]
    assert any(f["rule"] == "CW001" for f in result["findings"])


def test_target_only_attributes_changes_since_branch_target_merge_base(repo):
    # A's API removal is already on main; it must not be attributed to A again.
    repo.write("api.py", "def f(): pass\n")
    original = repo.commit("original")
    repo.branch("b", original)
    repo.write("api.py", "# removed\n")
    target = repo.commit("target removal")
    repo.branch("a", target)
    repo.checkout("a")
    repo.write("unrelated.txt", "a\n")
    repo.commit("a unrelated")
    repo.checkout("b")
    repo.write("client.py", "import api\napi.f()\n")
    repo.commit("b call")
    pairwise = payload(repo.check("--no-textual", "--format", "json"), 1)
    targeted = payload(repo.check("--target", "main", "--no-textual", "--format", "json"), 0)
    assert any(f["rule"] == "CW001" for f in pairwise["findings"])
    assert targeted["findings"] == []


def test_target_and_base_are_mutually_exclusive(repo):
    build_stale(repo)
    result = repo.check("--target", "main", "--base", "main")
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("crosswire: error:")


@pytest.mark.parametrize("option", [None, "--base", "--target"])
def test_unknown_revision_message(repo, option):
    build_stale(repo)
    args = [option, "missing-ref"] if option else []
    branches = ("a", "b") if option else ("a", "missing-ref")
    result = repo.check(*args, branches=branches)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "crosswire: error: unknown revision: missing-ref\n"


def test_prefilter_does_not_skip_textual_conflicts(repo):
    repo.pair({"readme.txt": "base\n"}, {"readme.txt": "a\n"}, {"readme.txt": "b\n"})
    report = payload(repo.check("--target", "main", "--format", "json"), 1)
    assert [f["rule"] for f in report["findings"]] == ["CW005"]


@pytest.mark.parametrize("scenario", ["definitions", "django", "alembic"])
def test_prefilter_preserves_definition_and_migration_interactions(repo, scenario):
    if scenario == "definitions":
        left, right, rule, code = {"api.py": "def f(): return 1\n"}, {"api.py": "def f(): return 2\n"}, "CW003", 0
    elif scenario == "django":
        left, right, rule, code = {"app/migrations/0007_a.py": ""}, {"app/migrations/0007_b.py": ""}, "CW004", 1
    else:
        left, right, rule, code = {"db/versions/a.py": "down_revision='p'\n"}, {"db/versions/b.py": "down_revision='p'\n"}, "CW004", 1
    repo.pair({}, left, right)
    report = payload(repo.check("--target", "main", "--no-textual", "--format", "json"), code)
    assert any(f["rule"] == rule for f in report["findings"])


def test_cache_off_cold_warm_outputs_identical(repo):
    build_stale(repo)
    disabled = repo.check("--no-cache", "--format", "json")
    assert disabled.returncode == 1, disabled.stderr
    assert not cache_dir(repo).exists()
    cold = repo.check("--format", "json")
    files = list(cache_dir(repo).glob("*.json"))
    assert files
    assert all(re.fullmatch(r"[0-9a-f]{64}\.json", p.name) for p in files)
    assert all(isinstance(json.loads(p.read_text()), dict) for p in files)
    warm = repo.check("--format", "json")
    assert (disabled.returncode, disabled.stdout, disabled.stderr) == (cold.returncode, cold.stdout, cold.stderr)
    assert (cold.returncode, cold.stdout, cold.stderr) == (warm.returncode, warm.stdout, warm.stderr)


def test_warm_cache_reuses_summary_without_diffing(repo, monkeypatch):
    from crosswire import git

    build_stale(repo)
    payload(repo.check("--format", "json"), 1)
    assert list(cache_dir(repo).glob("*.json"))
    calls = []
    original = git.changed_files

    def counted(repo, base, tip):
        calls.append((base, tip))
        return original(repo, base, tip)

    monkeypatch.setattr(git, "changed_files", counted)
    report = repo.analyze(textual=False)
    assert any(f.rule == "CW001" for f in report.findings)
    assert calls == [], "PLAN-v0.2 §12.3: valid cached summaries must be reused, not recomputed"


def test_no_cache_neither_reads_nor_rewrites_existing_entries(repo):
    build_stale(repo)
    expected = repo.check("--format", "json")
    files = list(cache_dir(repo).glob("*.json"))
    assert files
    for path in files:
        path.write_text("corrupt cache must be ignored with --no-cache")
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
    actual = repo.check("--no-cache", "--format", "json")
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in cache_dir(repo).glob("*.json")}
    assert actual.returncode == expected.returncode == 1
    assert actual.stdout == expected.stdout and actual.stderr == expected.stderr
    assert before == after


@pytest.mark.parametrize("content", ["{garbage", "{}", "null", "[]"])
def test_corrupt_cache_is_recomputed(repo, content):
    build_stale(repo)
    expected = repo.check("--format", "json")
    files = list(cache_dir(repo).glob("*.json"))
    assert files
    for path in files:
        path.write_text(content)
    actual = repo.check("--format", "json")
    assert actual.returncode == expected.returncode == 1
    assert actual.stdout == expected.stdout and actual.stderr == expected.stderr


def test_cache_roots_and_tip_are_part_of_key(repo):
    build_stale(repo)
    payload(repo.check("--format", "json"), 1)
    original = {p.name for p in cache_dir(repo).glob("*.json")}
    assert original
    payload(repo.check("--src", "nonexistent", "--format", "json"), 0)
    roots_changed = {p.name for p in cache_dir(repo).glob("*.json")}
    assert roots_changed > original
    repo.checkout("b")
    repo.write("client.py", "import api\napi.f(1)\napi.f(2)\n")
    repo.commit("new tip")
    payload(repo.check("--format", "json"), 1)
    assert {p.name for p in cache_dir(repo).glob("*.json")} > roots_changed


def test_cache_base_is_part_of_key(repo):
    before = repo.git("rev-parse", "HEAD").stdout.decode().strip()
    base = build_stale(repo)
    payload(repo.check("--base", base, "--format", "json"), 1)
    original = {p.name for p in cache_dir(repo).glob("*.json")}
    assert original
    payload(repo.check("--base", before, "--format", "json"), 0)
    assert {p.name for p in cache_dir(repo).glob("*.json")} > original


def test_cache_is_shared_through_git_common_dir(repo, tmp_path):
    build_stale(repo)
    linked = tmp_path / "linked-worktree"
    repo.git("worktree", "add", "--detach", str(linked), "a")
    result = repo.cli("check", "--repo", str(linked), "--format", "json", "a", "b")
    assert result.returncode == 1, result.stderr
    assert list(cache_dir(repo).glob("*.json"))
    assert not (linked / ".git/crosswire").exists()


@pytest.mark.parametrize("scenario", ["stale", "mixed_warning_and_textual"])
def test_sarif_shape_matches_json_findings_and_is_deterministic(repo, scenario):
    if scenario == "stale":
        build_stale(repo)
    else:
        repo.pair({}, {"api.py": "def f(): return 1\n"}, {"api.py": "def f(): return 2\n"})
    ordinary = payload(repo.check("--format", "json"), 1)
    first = repo.check("--format", "sarif")
    second = repo.check("--format", "sarif")
    sarif = payload(first, 1)
    assert first.stdout == second.stdout
    assert first.stdout.rstrip("\n") == json.dumps(sarif, sort_keys=True, indent=2)
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "crosswire"
    rules = run["tool"]["driver"]["rules"]
    assert {r["id"] for r in rules} == {f"CW00{i}" for i in range(1, 6)}
    assert all(isinstance(r["shortDescription"]["text"], str) and r["shortDescription"]["text"] for r in rules)
    assert len(run["results"]) == len(ordinary["findings"])
    for result, finding in zip(run["results"], ordinary["findings"], strict=True):
        assert result["ruleId"] == finding["rule"]
        assert result["level"] == finding["severity"]
        assert result["message"]["text"] == finding["message"]
        location = result["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == finding["path"]
        assert location["region"]["startLine"] == finding["line"]
        assert {key: result["properties"][key] for key in ("branch", "other_branch", "symbol")} == {key: finding[key] for key in ("branch", "other_branch", "symbol")}
        assert result["properties"]["hint"] == finding["hint"]
        assert result["properties"]["limitations"] == finding["limitations"]


def test_sarif_empty_results_and_warning_level(repo):
    repo.pair({}, {"api.py": "def f(): return 1\n"}, {"api.py": "def f(): return 2\n"})
    report = payload(repo.check("--format", "sarif", "--no-textual"), 0)
    assert report["runs"][0]["results"][0]["level"] == "warning"
    empty = payload(repo.check("--format", "sarif", "--src", "missing", "--no-textual"), 0)
    assert empty["runs"][0]["results"] == []
