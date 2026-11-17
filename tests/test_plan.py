"""S8: independent scenario truth tables plus exhaustive ordered-prefix CLI oracles."""

from itertools import permutations
import json

import pytest

from .test_combined import DIRECT, GAP
from .test_v03b import assert_coverage


def error_keys(report):
    return {(f["rule"], f["path"], f["symbol"] or f["path"]) for f in report["findings"] if f["severity"] == "error"}


class PrefixOracle:
    def __init__(self, repo, labels, unsafe):
        self.repo, self.labels, self.unsafe = repo, tuple(labels), unsafe
        self.results = {(): set()}
        base = repo.git("rev-parse", "main").stdout.decode().strip()
        repo.branch("oracle-empty", base)
        repo.checkout("oracle-empty")
        repo.commit("oracle empty commit")

    def errors(self, prefix):
        prefix = tuple(prefix)
        if prefix not in self.results:
            branches = prefix if len(prefix) >= 2 else ("oracle-empty", *prefix)
            result = self.repo.check("--target", "main", "--combined", "--format", "json", branches=branches)
            assert result.returncode in (0, 1), result.stderr
            report = json.loads(result.stdout)
            assert report["skipped"] == [], f"Oracle fixture has unexpected textual conflicts: {prefix}"
            keys = error_keys(report)
            assert bool(keys) is self.unsafe(set(prefix)), f"Combined checker disagrees with independent fixture oracle: {prefix}"
            self.results[prefix] = keys
        return self.results[prefix]

    def enumerate_all_orders(self):
        for order in permutations(self.labels):
            for length in range(1, len(order) + 1):
                self.errors(order[:length])

    def verify_plan(self, report):
        placed = []
        before = set()
        for step in report["steps"]:
            assert isinstance(step["reason"], str) and step["reason"].strip(), "B1 requires a safety explanation"
            assert type(step["together"]) is bool
            assert step["branches"] and not set(step["branches"]) & set(placed)
            after = self.errors((*placed, *step["branches"]))
            assert after <= before, f"Planner introduces new errors: {step}"
            if step["together"]:
                assert 2 <= len(step["branches"]) <= 3
                assert all(self.errors((*placed, branch)) - before for branch in step["branches"]), "A together group must be needed"
            placed.extend(step["branches"])
            before = after
        blocked = [entry["branch"] for entry in report["blocked"]]
        assert set(placed) | set(blocked) == set(self.labels)
        assert not set(placed) & set(blocked)
        for entry in report["blocked"]:
            assert entry["findings"]
            reported = error_keys(entry)
            assert reported and reported <= self.errors((*placed, entry["branch"])) - before
            if any(f["rule"] == "CW001" for f in entry["findings"]):
                assert isinstance(entry.get("hint"), str) and entry["hint"].strip(), "Restoring a removed API is a justified hint"
        assert report["summary"] == {"placed": len(placed), "blocked": len(blocked)}
        assert_coverage(report)
        return placed


def plan(repo, labels, code=0, **kwargs):
    options = kwargs.get("options", [])
    result = repo.cli("plan", "--repo", str(repo.path), "--target", "main", "--format", "json", *options, *labels)
    assert result.returncode == code, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["version"] == 2 and report["tool"] == "crosswire" and report["mode"] == "plan"
    assert report["target"] == repo.git("rev-parse", "main").stdout.decode().strip()
    assert result.stdout.rstrip("\n") == json.dumps(report, sort_keys=True, indent=2)
    return report, result.stdout


def test_s8_fixed_by_third_all_orders_and_fix_precedes_removal(repo):
    source = DIRECT + GAP + "# export slot\n"
    repo.named_dag(
        {"m.py": source, "compat.py": DIRECT, "existing.py": "import m\nm.f(1)\n"},
        {"A": ("target", {"m.py": source.replace(DIRECT, "# removed\n", 1)}),
         "B": ("target", {"m.py": source + "from compat import f\n"}),
         "C": ("target", {"use.py": "import m\nm.f(1)\n"})},
    )
    oracle = PrefixOracle(repo, ("A", "B", "C"), lambda present: "A" in present and "B" not in present)
    oracle.enumerate_all_orders()
    for order in permutations(oracle.labels):
        report, raw = plan(repo, order)
        placed = oracle.verify_plan(report)
        assert placed.index("B") < placed.index("A")
        assert all(not step["together"] for step in report["steps"])
        if order == ("A", "B", "C"):
            fix_step = next(step for step in report["steps"] if step["branches"] == ["B"])
            expected_reason = "placed before A: A would break `m.f` (CW001, culprits A); resolves CW001 of main (m.f)"
            assert fix_step["reason"] == expected_reason
            text = repo.cli("plan", "--repo", str(repo.path), "--target", "main", *order)
            assert text.returncode == 0
            assert "1. B — " + expected_reason in text.stdout
        assert plan(repo, order)[1] == raw


def test_s8_only_jointly_clean_branches_form_atomic_together_step(repo):
    m = DIRECT + GAP + "# m export slot\n"
    n = DIRECT.replace("f(", "g(") + GAP + "# n export slot\n"
    repo.named_dag(
        {"m.py": m, "n.py": n, "compat.py": DIRECT + DIRECT.replace("f(", "g("),
         "existing_m.py": "import m\nm.f(1)\n", "existing_n.py": "import n\nn.g(1)\n"},
        {"A": ("target", {"m.py": m.replace(DIRECT, "# removed f\n", 1), "n.py": n + "from compat import g\n"}),
         "B": ("target", {"n.py": n.replace(DIRECT.replace("f(", "g("), "# removed g\n", 1), "m.py": m + "from compat import f\n"}),
         "D": ("target", {"decoy.txt": "safe\n"})},
    )
    oracle = PrefixOracle(repo, ("A", "B", "D"), lambda present: ("A" in present) != ("B" in present))
    oracle.enumerate_all_orders()
    for order in permutations(oracle.labels):
        report, _ = plan(repo, order)
        oracle.verify_plan(report)
        groups = [step for step in report["steps"] if step["together"]]
        assert len(groups) == 1 and set(groups[0]["branches"]) == {"A", "B"}


def test_s8_unfixable_four_branch_set_has_blocked_reasons_and_hints(repo):
    base = {"m.py": DIRECT, "n.py": DIRECT, "p.py": DIRECT,
            "existing.py": "import m\nimport n\nimport p\nm.f(1)\nn.f(1)\np.f(1)\n"}
    repo.named_dag(base, {
        "A": ("target", {"m.py": "# removed\n"}),
        "B": ("target", {"n.py": "# removed\n"}),
        "C": ("target", {"p.py": "# removed\n"}),
        "D": ("target", {"decoy.txt": "safe\n"}),
    })
    oracle = PrefixOracle(repo, ("A", "B", "C", "D"), lambda present: bool(present & {"A", "B", "C"}))
    oracle.enumerate_all_orders()
    for order in [("A", "B", "C", "D"), ("D", "C", "B", "A")]:
        report, _ = plan(repo, order, 1)
        assert oracle.verify_plan(report) == ["D"]
        assert [entry["branch"] for entry in report["blocked"]] == [branch for branch in order if branch != "D"]


def test_s8_five_branch_stack_all_orders_and_containment_constraints(repo):
    repo.named_dag({}, {
        "A": ("target", {"a.py": "value = 1\n"}),
        "B": ("A", {"b.py": "value = 2\n"}),
        "C": ("B", {"c.py": "value = 3\n"}),
        "D": ("target", {"d.py": "value = 4\n"}),
        "E": ("target", {"e.py": "value = 5\n"}),
    })
    oracle = PrefixOracle(repo, ("A", "B", "C", "D", "E"), lambda present: False)
    oracle.enumerate_all_orders()
    for order in [("C", "B", "A", "D", "E"), ("E", "D", "C", "A", "B"), ("A", "B", "C", "D", "E")]:
        report, _ = plan(repo, order)
        placed = oracle.verify_plan(report)
        assert placed.index("A") < placed.index("B") < placed.index("C")
        assert report["contained_in"]["A"] == ["B", "C"]
        assert report["contained_in"]["B"] == ["C"]
        assert all(not step["together"] for step in report["steps"])


def test_plan_accepts_single_branch_and_reports_bounded_large_group_search(repo):
    repo.named_dag({"m.py": DIRECT, "existing.py": "import m\nm.f(1)\n"}, {
        **{f"A{i}": ("target", {"m.py": "# removed\n", f"unique_{i}.txt": str(i)}) for i in range(9)},
    })
    single, _ = plan(repo, ("A0",), 1)
    assert single["summary"] == {"placed": 0, "blocked": 1}
    assert_coverage(single)
    report, _ = plan(repo, tuple(f"A{i}" for i in range(9)), 1)
    assert_coverage(report, False)
    assert report["summary"] == {"placed": 0, "blocked": 9}
    text = repo.cli("plan", "--repo", str(repo.path), "--target", "main", *[f"A{i}" for i in range(9)])
    assert text.returncode == 1
    assert "Coverage: bounded (" in text.stdout
    assert "unchecked combinations are not proven safe." in text.stdout


def test_plan_state_migration_rule_checks_existing_target_migrations(repo):
    repo.named_dag({"app/migrations/0001_base.py": "# base\n"}, {
        "A": ("target", {"app/migrations/0001_new.py": "# collision\n"}),
    })
    report, _ = plan(repo, ("A",), 1)
    assert report["steps"] == [] and report["blocked"][0]["branch"] == "A"
    assert any(f["rule"] == "CW004" for f in report["blocked"][0]["findings"])


def test_plan_preexisting_target_migration_errors_do_not_block_unrelated_branch(repo):
    repo.named_dag({"app/migrations/0001_base.py": "# one\n", "app/migrations/0001_other.py": "# two\n"}, {
        "A": ("target", {"safe.txt": "safe\n"}),
    })
    report, _ = plan(repo, ("A",))
    assert report["summary"] == {"placed": 1, "blocked": 0}


def test_plan_requires_target_and_at_least_one_branch(repo):
    repo.named_dag({}, {"A": ("target", {"safe.txt": "safe\n"})})
    for args in [("A",), ("--target", "main")]:
        result = repo.cli("plan", "--repo", str(repo.path), *args)
        assert result.returncode == 2 and result.stdout == ""
        assert result.stderr.startswith("crosswire: error:")


def test_b1_blocked_textual_conflict_has_specific_rebase_hint(repo):
    repo.named_dag({"conflict.txt": "base\n"}, {
        "A": ("target", {"conflict.txt": "feature\n"}),
        "D": ("target", {"safe.txt": "safe\n"}),
    })
    repo.checkout("main")
    repo.write("conflict.txt", "target changed\n")
    repo.commit("advance target")
    report, _ = plan(repo, ("A", "D"), 1)
    assert report["summary"] == {"placed": 1, "blocked": 1}
    blocked = report["blocked"][0]
    assert blocked["branch"] == "A"
    assert any(f["rule"] == "CW005" for f in blocked["findings"])
    assert blocked["hint"] == "rebase A onto main (conflicts in conflict.txt)"


def test_b1_blocked_cw005_names_culprits_in_message_and_hint(repo):
    repo.named_dag({"conflict.txt": "base\n"}, {
        "R": ("target", {"conflict.txt": "left\n"}),
        "B": ("target", {"conflict.txt": "right\n"}),
        "D": ("target", {"safe.txt": "safe\n"}),
    })
    report, _ = plan(repo, ("R", "B", "D"), 1)
    assert report["summary"] == {"placed": 2, "blocked": 1}
    entry = report["blocked"][0]
    assert entry["branch"] == "B"
    assert entry["hint"] == "rebase B onto R (conflicts in conflict.txt)"
    assert len(entry["findings"]) == 1
    finding = entry["findings"][0]
    assert finding["rule"] == "CW005" and finding["culprits"] == ["R"]
    assert finding["message"] == "textual conflict with R"
    text = repo.cli("plan", "--repo", str(repo.path), "--target", "main", "R", "B", "D")
    assert text.returncode == 1
    assert "textual conflict with R — rebase B onto R (conflicts in conflict.txt)" in text.stdout
