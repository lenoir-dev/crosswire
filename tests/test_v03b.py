"""Public contract regressions for PLAN-v0.3b T12, T11, T10 and B1."""

import json
from pathlib import Path
import subprocess

import pytest

from .test_combined import DIRECT, FALLBACK, GAP, combined, native_pairs_clean


def assert_coverage(report, complete=True):
    assert report["coverage"] == ("complete" if complete else "bounded")
    limits = report["limits"]
    assert set(limits) == {"max_candidates", "max_group", "group_search_max_remaining", "hit"}
    assert (limits["max_candidates"], limits["max_group"], limits["group_search_max_remaining"]) == (6, 3, 8)
    assert isinstance(limits["hit"], list)
    assert bool(limits["hit"]) is (not complete)


@pytest.mark.parametrize("mode", ["pairwise", "combined"])
def test_t12_coalesces_import_and_calls_at_first_line_per_owner(repo, mode):
    repo.named_dag(
        {"m.py": DIRECT},
        {"A": ("target", {"m.py": "# removed\n"}),
         "C": ("target", {"use.py": "from m import f\nf(1)\nf(2)\n"})},
    )
    options = ["--combined", "--target", "main"] if mode == "combined" else []
    result = repo.check(*options, "--format", "json", branches=("A", "C"))
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert (finding["rule"], finding["branch"], finding["path"], finding["line"]) == ("CW001", "C", "use.py", 1)
    assert finding["message"].endswith(" (3 uses in this file)")
    assert report["summary"] == {"errors": 1, "warnings": 0}


def test_t12_different_files_and_symbols_remain_separate(repo):
    repo.named_dag(
        {"m.py": DIRECT + "def g(value): return value\n"},
        {"A": ("target", {"m.py": "# removed\n"}),
         "C": ("target", {"one.py": "import m\nm.f(1)\nm.f(2)\nm.g(3)\n", "two.py": "import m\nm.f(1)\n"})},
    )
    report = combined(repo, ("A", "C"), 1)
    assert len(report["findings"]) == 3
    assert {(f["path"], f["symbol"]) for f in report["findings"]} == {("one.py", "m.f"), ("one.py", "m.g"), ("two.py", "m.f")}


@pytest.mark.parametrize("mode", ["pairwise", "combined"])
def test_t12_same_line_uses_are_counted_before_deduplication(repo, mode):
    repo.named_dag({"m.py": DIRECT}, {
        "A": ("target", {"m.py": "# removed\n"}),
        "C": ("target", {"use.py": "from m import f\nf(1); f(2)\n"}),
    })
    options = ["--combined", "--target", "main"] if mode == "combined" else []
    result = repo.check(*options, "--format", "json", branches=("A", "C"))
    assert result.returncode == 1
    findings = json.loads(result.stdout)["findings"]
    assert len(findings) == 1 and findings[0]["line"] == 1
    assert findings[0]["message"].endswith(" (3 uses in this file)")


def test_t11_skipped_branch_has_minimal_culprits_excluding_unrelated_prefix(repo):
    repo.named_dag(
        {"conflict.txt": "base\n"},
        {"A": ("target", {"conflict.txt": "left\n"}),
         "D": ("target", {"unrelated.txt": "decoy\n"}),
         "X": ("target", {"conflict.txt": "right\n"})},
    )
    report = combined(repo, ("A", "D", "X"), 1)
    hit = next(f for f in report["findings"] if f["rule"] == "CW005")
    assert hit["branch"] == "X" and hit["culprits"] == ["A"]
    assert hit["culprits_exact"] is True
    assert hit["message"] == "textual conflict with A"
    assert report["integrated"] == ["A", "D"]
    assert_coverage(report)


def test_t11_more_than_six_candidates_is_inexact_and_explicitly_bounded(repo):
    source = "".join(f"value_{i} = 0\n" + GAP for i in range(7))
    changes = {f"A{i}": ("target", {"same.py": source.replace(f"value_{i} = 0", f"value_{i} = 1")}) for i in range(7)}
    changes["X"] = ("target", {"same.py": source.replace("value_0 = 0", "value_0 = 2")})
    repo.named_dag({"same.py": source}, changes)
    report = combined(repo, (*[f"A{i}" for i in range(7)], "X"), 1)
    hit = next(f for f in report["findings"] if f["rule"] == "CW005")
    assert hit["branch"] == "X" and hit["culprits"] == [f"A{i}" for i in range(7)]
    assert hit["culprits_exact"] is False
    assert hit["message"] == "textual conflict with " + ", ".join(hit["culprits"])
    assert_coverage(report, False)


@pytest.mark.parametrize("replacement,rule", [("# f removed\n", "CW001"), ("def f(value, required): pass\n", "CW002")])
def test_t10_unchanged_target_caller_is_checked(repo, replacement, rule):
    repo.named_dag(
        {"m.py": DIRECT, "use.py": "import m\nm.f(1)\n"},
        {"A": ("target", {"m.py": replacement}), "D": ("target", {"unrelated.txt": "decoy\n"})},
    )
    report = combined(repo, ("A", "D"), 1)
    assert len(report["findings"]) == 1
    hit = report["findings"][0]
    assert (hit["rule"], hit["branch"], hit["culprits"], hit["path"], hit["line"]) == (rule, "main", ["A"], "use.py", 2)
    assert hit["culprits_exact"] is True and hit["location"] == "integrated"
    assert_coverage(report)
    pairwise = repo.check("--target", "main", "--format", "json", branches=("A", "D"))
    assert pairwise.returncode == 0 and json.loads(pairwise.stdout)["findings"] == []


def test_t10_conjunctive_removal_breaks_target_reference_with_two_culprits(repo):
    source = DIRECT + GAP + FALLBACK
    repo.named_dag(
        {"m.py": source, "fast.py": DIRECT, "use.py": "import m\nm.f(1)\n"},
        {"A": ("target", {"m.py": source.replace(DIRECT, "# direct removed\n", 1)}),
         "B": ("target", {"m.py": source.replace(FALLBACK, "# fallback removed\n")})},
    )
    report = combined(repo, ("A", "B"), 1)
    assert len(report["findings"]) == 1
    hit = report["findings"][0]
    assert (hit["rule"], hit["branch"], hit["culprits"]) == ("CW006", "main", ["A", "B"])
    assert hit["culprits_exact"] is True


def test_t10_target_label_is_preserved_and_existing_errors_are_ignored(repo):
    commits = repo.named_dag(
        {"m.py": DIRECT, "use.py": "import m\nm.f(1)\nm.never_existed()\n"},
        {"A": ("target", {"m.py": "# removed\n"}), "D": ("target", {"other.txt": "other\n"})},
    )
    repo.branch("release-target", commits["target"])
    result = repo.check("--target", "release-target", "--combined", "--format", "json", branches=("A", "D"))
    assert result.returncode == 1
    findings = json.loads(result.stdout)["findings"]
    assert len(findings) == 1 and findings[0]["symbol"] == "m.f" and findings[0]["branch"] == "release-target"


def test_t10_multiset_separates_target_uses_from_branch_added_uses(repo):
    original = "import m\nm.f(1)\n"
    repo.named_dag(
        {"m.py": DIRECT, "use.py": original},
        {"A": ("target", {"m.py": "# removed\n"}), "C": ("target", {"use.py": original + "m.f(1)\n"})},
    )
    report = combined(repo, ("A", "C"), 1)
    hits = report["findings"]
    assert len(hits) == 2
    assert {(f["branch"], f["line"]) for f in hits} == {("main", 2), ("C", 3)}
    assert all(f["culprits"] == ["A"] for f in hits)
    assert all("uses in this file" not in f["message"] for f in hits)


@pytest.mark.parametrize("call", ["m.f()", "m.f(*args)", "m.f(1, **kwargs)"])
def test_t10_preexisting_bad_arity_and_splatted_target_calls_are_ignored(repo, call):
    repo.named_dag({"m.py": DIRECT, "use.py": "import m\n" + call + "\n"}, {
        "A": ("target", {"m.py": "def f(value, required): pass\n"}),
        "D": ("target", {"decoy.txt": "safe\n"}),
    })
    report = combined(repo, ("A", "D"), 0)
    assert report["findings"] == []


@pytest.mark.parametrize("replacement", [None, "import compat\ncompat.f(1)\n"])
def test_t10_target_uses_removed_or_redirected_in_final_state_are_not_reported(repo, replacement):
    repo.named_dag({"m.py": DIRECT, "compat.py": DIRECT, "use.py": "import m\nm.f(1)\n"}, {
        "A": ("target", {"m.py": "# removed\n"}),
        "D": ("target", {"use.py": replacement}),
    })
    assert combined(repo, ("A", "D"), 0)["findings"] == []


def test_t13_blob_reads_reuse_one_batch_process_with_odd_paths(repo, monkeypatch):
    from crosswire.git import read_file

    repo.write("batch unique space.py", "first = 1\n")
    repo.write("batch\nnewline.py", "second = 2\n")
    sha = repo.commit("unique batched blobs")
    spawned = []
    original = subprocess.Popen

    def counted(args, *positional, **kwargs):
        if isinstance(args, (list, tuple)) and "cat-file" in args:
            spawned.append(tuple(args))
        return original(args, *positional, **kwargs)

    with repo.unchanged():
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", counted)
            assert read_file(repo.path, sha, "batch unique space.py") == "first = 1\n"
            assert read_file(repo.path, sha, "batch\nnewline.py") == "second = 2\n"
            assert read_file(repo.path, sha, "batch missing.py") is None
            assert read_file(repo.path, sha, "batch unique space.py") == "first = 1\n"
    assert len(spawned) == 1, "T13 requires one long-lived cat-file process per repository"
    assert any(arg.startswith("--batch") for arg in spawned[0])


def test_t13_tree_listing_and_merge_base_are_memoized_for_immutable_revisions(repo, monkeypatch):
    from crosswire.git import list_files, merge_base

    commits = repo.named_dag({"memo-base.txt": "base\n"}, {
        "A": ("target", {"memo-a.txt": "a\n"}), "B": ("target", {"memo-b.txt": "b\n"}),
    })
    commands = []
    original = subprocess.Popen

    def counted(args, *positional, **kwargs):
        if isinstance(args, (list, tuple)) and ("ls-tree" in args or "merge-base" in args):
            commands.append(tuple(args))
        return original(args, *positional, **kwargs)

    with repo.unchanged(), monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", counted)
        assert list_files(repo.path, commits["A"]) == list_files(repo.path, commits["A"])
        assert merge_base(repo.path, commits["A"], commits["B"]) == commits["target"]
        assert merge_base(repo.path, commits["A"], commits["B"]) == commits["target"]
    assert sum("ls-tree" in command for command in commands) == 1
    assert sum("merge-base" in command for command in commands) == 1


def test_t13_memoization_does_not_make_moving_refs_stale(repo):
    from crosswire.git import list_files, merge_base

    commits = repo.named_dag({}, {"A": ("target", {"a.txt": "a\n"}), "B": ("target", {"b.txt": "b\n"})})
    with repo.unchanged():
        assert merge_base(repo.path, "A", "B") == commits["target"]
        assert list_files(repo.path, "A") == ["a.txt"]
    repo.checkout("main")
    repo.git("branch", "-f", "B", "A")
    repo.checkout("A")
    repo.write("new.txt", "new\n")
    repo.commit("move A")
    with repo.unchanged():
        assert merge_base(repo.path, "A", "B") == commits["A"]
        assert set(list_files(repo.path, "A")) == {"a.txt", "new.txt"}
