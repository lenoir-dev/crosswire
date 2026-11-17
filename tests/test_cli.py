"""PLAN §1/§7/§8/§10: executable interface and wire-format guarantees."""

import json
import re

import pytest


def clean_pair(repo):
    return repo.pair({}, {"left.txt": "left\n"}, {"right.txt": "right\n"})


def stale_pair(repo):
    return repo.pair(
        {"billing.py": "def charge(amount): return amount\n"},
        {"billing.py": "def create_charge(amount): return amount\n"},
        {"client.py": "import billing\nbilling.charge(1)\n"},
    )


def assert_usage_error(result):
    assert result.returncode == 2, result.stderr
    assert result.stdout == ""
    assert "crosswire: error: " in result.stderr


def test_cli_clean_exit_zero_and_text(repo):
    clean_pair(repo)
    result = repo.check()
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.strip() == "No semantic conflicts found across 1 pair(s)."


def test_cli_error_exit_one_and_text_location(repo):
    stale_pair(repo)
    result = repo.check()
    assert result.returncode == 1, result.stderr
    assert "client.py:2: ERROR CW001 [b × a]" in result.stdout
    assert "1 error(s), 0 warning(s) across 1 pair(s)" in result.stdout


def test_cli_warnings_only_exit_zero(repo):
    repo.pair({}, {"api.py": "def f(): return 1\n"}, {"api.py": "def f(): return 2\n"})
    result = repo.check("--no-textual")
    assert result.returncode == 0, result.stderr
    assert "WARNING CW003" in result.stdout
    assert "0 error(s), 1 warning(s)" in result.stdout


@pytest.mark.parametrize("branches", [("a",), ("a", "a"), ("a", "not-a-ref")])
def test_cli_usage_and_ref_errors(repo, branches):
    clean_pair(repo)
    assert_usage_error(repo.check(branches=branches))


def test_cli_duplicate_resolved_sha_is_usage_error(repo):
    clean_pair(repo)
    repo.branch("alias", "a")
    assert_usage_error(repo.check(branches=("a", "alias")))


def test_cli_same_commit_by_sha_and_label_is_usage_error(repo):
    clean_pair(repo)
    sha = repo.git("rev-parse", "a").stdout.decode().strip()
    assert_usage_error(repo.check(branches=("a", sha)))


def test_cli_bad_format_and_missing_command(repo):
    clean_pair(repo)
    assert_usage_error(repo.check("--format", "invalid"))
    assert_usage_error(repo.cli("check"))


def test_cli_invalid_repo(repo, tmp_path):
    outside = tmp_path / "not-a-repository"
    outside.mkdir()
    result = repo.cli("check", "--repo", str(outside), "a", "b")
    assert_usage_error(result)


def test_cli_repo_can_be_nested_directory(repo):
    clean_pair(repo)
    inside = repo.path / "nested" / "directory"
    inside.mkdir(parents=True)
    result = repo.cli("check", "--repo", str(inside), "a", "b")
    assert result.returncode == 0, result.stderr


def test_cli_default_repo_is_current_directory(repo):
    clean_pair(repo)
    result = repo.cli("check", "a", "b", cwd=repo.path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("option", ["--help", "--version"])
def test_cli_help_and_version(repo, option):
    result = repo.cli(option)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert result.stderr == ""


def test_cli_valid_explicit_base(repo):
    base = clean_pair(repo)
    result = repo.check("--base", base, "--format", "json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pairs"] == [{"a": "a", "b": "b", "base": base}]


@pytest.mark.parametrize("base", ["a", "not-a-ref"])
def test_cli_invalid_or_nonancestor_explicit_base(repo, base):
    clean_pair(repo)
    assert_usage_error(repo.check("--base", base))


def test_cli_no_common_ancestor(repo):
    repo.branch("a")
    repo.git("checkout", "--orphan", "b")
    repo.write("other.txt", "other\n")
    repo.commit("unrelated")
    assert_usage_error(repo.check())


def test_cli_no_textual_disables_conflicts(repo):
    repo.pair({"readme.txt": "base\n"}, {"readme.txt": "left\n"}, {"readme.txt": "right\n"})
    assert repo.check().returncode == 1
    assert repo.check("--no-textual").returncode == 0


def test_json_exact_shape_sorted_keys_and_repeatability(repo):
    base = stale_pair(repo)
    first = repo.check("--format", "json")
    second = repo.check("--format", "json")
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr == ""
    payload = json.loads(first.stdout)
    assert set(payload) == {"version", "tool", "pairs", "findings", "summary"}
    assert payload["version"] == 1
    assert payload["tool"] == "crosswire"
    assert payload["pairs"] == [{"a": "a", "b": "b", "base": base}]
    assert payload["summary"] == {"errors": 1, "warnings": 0}
    assert len(payload["findings"]) == 1
    finding = payload["findings"][0]
    assert set(finding) == {
        "rule", "severity", "message", "branch", "other_branch", "path", "line", "symbol",
    }
    assert finding["rule"] == "CW001"
    assert finding["severity"] == "error"
    assert finding["path"] == "client.py"
    assert finding["line"] == 2 and type(finding["line"]) is int
    assert finding["symbol"] == "billing.charge"
    assert finding["branch"] == "b" and finding["other_branch"] == "a"
    assert isinstance(finding["message"], str)
    assert str(repo.path) not in first.stdout
    assert first.stdout.rstrip("\n") == json.dumps(payload, sort_keys=True, indent=2)


def test_json_empty_report(repo):
    clean_pair(repo)
    result = repo.check("--format", "json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["findings"] == []
    assert payload["summary"] == {"errors": 0, "warnings": 0}


def test_json_pairs_preserve_input_combinations_and_user_labels(repo):
    base = clean_pair(repo)
    repo.branch("z", base)
    repo.checkout("z")
    repo.write("third.txt", "third\n")
    repo.commit("third")
    result = repo.check("--format", "json", branches=("z", "b", "a"))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pairs"] == [
        {"a": "z", "b": "b", "base": base},
        {"a": "z", "b": "a", "base": base},
        {"a": "b", "b": "a", "base": base},
    ]


def test_json_findings_deduplicated_and_sorted(repo):
    repo.pair(
        {"billing.py": "def charge(amount): pass\n"},
        {"billing.py": ""},
        {"z.py": "import billing\nbilling.charge(1)\n",
         "a.py": "import billing\nbilling.charge(1)\nbilling.charge(2)\n"},
    )
    result = repo.check("--format", "json")
    payload = json.loads(result.stdout)
    hits = payload["findings"]
    key = lambda f: (f["path"], f["line"], f["rule"], f["branch"], f["other_branch"], f["symbol"] or "", f["message"])
    assert hits == sorted(hits, key=key)
    identities = [(f["rule"], f["branch"], f["other_branch"], f["path"], f["line"], f["symbol"]) for f in hits]
    assert len(identities) == len(set(identities))
    assert len(hits) == 3


def escape(value, property_value=False):
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if property_value else value


def test_github_annotation_escapes_properties_and_message(repo):
    path = "odd %,colon:\r\nfile.txt"
    repo.pair({path: "base\n"}, {path: "left\n"}, {path: "right\n"})
    raw = repo.check("--format", "json")
    github = repo.check("--format", "github")
    assert raw.returncode == github.returncode == 1
    finding = json.loads(raw.stdout)["findings"][0]
    assert github.stdout.strip("\n") == (
        f"::error file={escape(path, True)},line=1,title=CW005::{escape(finding['message'])}"
    )
    assert "%25" in github.stdout
    assert "%2C" in github.stdout and "%3A" in github.stdout
    assert "%0D" in github.stdout and "%0A" in github.stdout
    assert "\r" not in github.stdout


def test_github_warning_annotation(repo):
    repo.pair({}, {"api.py": "def f(): return 1\n"}, {"api.py": "def f(): return 2\n"})
    result = repo.check("--no-textual", "--format", "github")
    assert result.returncode == 0
    assert result.stdout.startswith("::warning file=api.py,line=1,title=CW003::")


def test_parse_failures_warn_on_stderr_and_skip_revision(repo):
    repo.pair({}, {"a.txt": "left\n"}, {"broken.py": "def broken(\n"})
    result = repo.check("--format", "json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["findings"] == []
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert re.fullmatch(r"crosswire: warning: cannot parse broken\.py@[0-9a-f]{7,40}", lines[0])


def test_parse_diagnostic_is_not_repeated_for_same_revision_across_pairs(repo):
    base = clean_pair(repo)
    repo.branch("broken", base)
    repo.checkout("broken")
    repo.write("broken.py", "def broken(\n")
    repo.commit("broken")
    result = repo.check("--format", "json", branches=("a", "b", "broken"))
    assert result.returncode == 0
    assert json.loads(result.stdout)["findings"] == []
    assert len(result.stderr.splitlines()) == 1


def test_github_message_percent_and_newline_escaping(repo):
    # CW001 messages include the changing branch's user-supplied label. Git permits '%'.
    repo.pair(
        {"api.py": "def f(): pass\n"}, {"api.py": ""},
        {"client.py": "import api\napi.f()\n"}, names=("remove%api", "consumer"),
    )
    raw = repo.check("--format", "json", branches=("remove%api", "consumer"))
    github = repo.check("--format", "github", branches=("remove%api", "consumer"))
    finding = json.loads(raw.stdout)["findings"][0]
    assert github.returncode == 1
    assert github.stdout.strip("\n").endswith("::" + escape(finding["message"]))
    assert "remove%25api" in github.stdout


def test_source_roots_explicit_and_repeatable(repo):
    repo.pair(
        {"lib/billing.py": "def charge(amount): pass\n", "clients/__init__.py": ""},
        {"lib/billing.py": ""},
        {"clients/client.py": "import billing\nbilling.charge(1)\n"},
    )
    default = repo.check("--format", "json")
    assert default.returncode == 0
    explicit = repo.check("--src", "lib", "--src", "clients", "--format", "json")
    assert explicit.returncode == 1, explicit.stderr
    assert any(f["rule"] == "CW001" for f in json.loads(explicit.stdout)["findings"])


def test_default_source_roots_use_src_at_pair_base(repo):
    repo.pair(
        {"src/billing.py": "def charge(amount): pass\n"},
        {"src/billing.py": None},
        {"client.py": "import billing\nbilling.charge(1)\n"},
    )
    result = repo.check("--format", "json")
    assert result.returncode == 1, result.stderr
    assert any(f["symbol"] == "billing.charge" for f in json.loads(result.stdout)["findings"])


def test_analysis_preserves_dirty_index_worktree_untracked_files_and_refs(repo):
    stale_pair(repo)
    repo.write("staged.txt", "staged\n")
    repo.git("add", "staged.txt")
    repo.write("staged.txt", "unstaged changes\n")
    repo.write("untracked.txt", "leave this alone\n")
    repo.write("client.py", "# uncommitted content must not affect committed analysis\n")
    report = repo.analyze()
    assert any(f.rule == "CW001" for f in report.findings)
    result = repo.check("--format", "json")
    assert result.returncode == 1
    assert any(f["rule"] == "CW001" for f in json.loads(result.stdout)["findings"])
