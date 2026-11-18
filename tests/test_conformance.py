"""Fast S16 template, fail-closed apparatus and installed-subprocess CI subset."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from conformance import git, oracle, run
from conformance.render.python import apply, render


CASES = run.load_cases()


def case_named(name):
    return next(item for item in CASES if item[2]["id"] == name)


@pytest.mark.parametrize("item", CASES, ids=[item[2]["id"] for item in CASES])
def test_renderer_is_deterministic_and_does_not_mutate_template(item):
    _, template, case = item
    before = deepcopy(template)
    first = render(template,case)
    assert first == render(template,case) and template == before
    assert len(first["branches"]) == len(case["branches"])
    assert first["sites"]["call"]["path"] == "consumer.py"
    for branch in first["branches"]:
        for path,content in branch["files"].items():
            assert not Path(path).is_absolute()
            if content is not None:compile(content,path,"exec")


def test_templates_declare_neutral_operations_and_explicit_language_support():
    assert len(CASES)==16
    for path,template,case in CASES:
        raw=path.read_text()
        assert "def " not in raw and "import " not in raw and ".py" not in raw
        assert set(case["expected"])==set(run.MODES)
        assert template["contracts"]["python"]["id"].startswith("PY-")
        if template["id"] in {"conjunctive","open_dynamic","open_wildcard"}:
            assert template["contracts"]["go"]["id"] is None


def test_sources_and_commit_ids_repeat_across_independent_repositories(tmp_path):
    _,template,case=case_named("fix_by_third-conflict")
    rendered=render(template,case)
    values=[]
    for name in ("first","second"):
        repo=tmp_path/name
        target,tips=git.build(repo,rendered)
        integrated=git.integrate(repo,target,tips,tuple(tips))
        values.append((target,tips,integrated,git.files_at(repo,integrated)))
    assert values[0]==values[1]


def test_unsupported_renderer_operation_is_explicit():
    _,template,_=case_named("rename-conflict")
    with pytest.raises(ValueError,match="Unsupported Python operation"):
        apply(template["base"],[{"op":"future-language-operation"}])


def test_oracle_disagreement_prevents_product_execution(tmp_path,monkeypatch):
    path,template,case=case_named("rename-conflict")
    monkeypatch.setattr(run,"check",lambda *args:{"verdict":"valid","runtime":{"verdict":"valid"},"diagnostics":[]})
    invoked=[]
    monkeypatch.setattr(run,"invoke_detector",lambda *args:invoked.append(args))
    with pytest.raises(oracle.KitBug,match="Oracle/template disagreement"):
        run.run_case(path,template,case,tmp_path/"result",sys.executable,sys.executable)
    assert not invoked
    assert json.loads((tmp_path/"result/result.json").read_text())["status"]=="kit-bug"
    assert not (tmp_path/"result/detector.json").exists()


@pytest.mark.parametrize("version,analyzed",[("wrong",1),(oracle.PIN,0)])
def test_wrong_or_incomplete_checker_output_is_a_kit_bug(tmp_path,monkeypatch,version,analyzed):
    data={"version":version,"generalDiagnostics":[],"summary":{"filesAnalyzed":analyzed,"errorCount":0}}
    calls=[]
    def fake(*args,**kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args,0,json.dumps(data).encode(),b"")
    monkeypatch.setattr(oracle.subprocess,"run",fake)
    with pytest.raises(oracle.KitBug):oracle.check({"m.py":b"value = 1\n"},tmp_path/"state",sys.executable)
    assert len(calls)==1


def test_unknown_requires_a_gap_and_cannot_hide_a_supported_conflict():
    _,template,case=case_named("open_dynamic-boundary")
    rendered=render(template,case)
    report={"findings":[],"coverage":"partial","limitations":{}}
    with pytest.raises(AssertionError,match="explicit gap"):
        run.assert_detector(case,"pairwise",report,0,rendered["sites"],{})
    report["limitations"]={"open-module":{"count":1}}
    run.assert_detector(case,"pairwise",report,0,rendered["sites"],{})
    _,template,case=case_named("rename-conflict")
    with pytest.raises(AssertionError,match="expected broken"):
        run.assert_detector(case,"pairwise",report,0,render(template,case)["sites"],{})


def test_moved_module_matches_module_identity_without_copying_symbol_from_case():
    _,template,case=case_named("move_module-conflict")
    sites=render(template,case)["sites"]
    finding={"rule":"CW001","severity":"error","path":"consumer.py","line":1,"symbol":"api.f"}
    report={"findings":[finding],"coverage":"complete"}
    run.assert_detector(case,"pairwise",report,1,sites,{})
    finding["symbol"]="api.another_name"
    run.assert_detector(case,"pairwise",report,1,sites,{})
    finding["symbol"]="stable.f"
    with pytest.raises(AssertionError,match="unrelated symbol/module"):
        run.assert_detector(case,"pairwise",report,1,sites,{})


def test_plan_checks_every_accepted_prefix_against_oracle():
    _,template,case=case_named("fix_by_third-conflict")
    report={"blocked":[],"coverage":"complete","steps":[{"branches":[label]} for label in ("A","B","C")]}
    observations={"A":{"verdict":"valid"},"A+B":{"verdict":"broken"},"A+B+C":{"verdict":"valid"}}
    with pytest.raises(AssertionError,match="oracle-failing prefix"):
        run.assert_detector(case,"plan",report,0,render(template,case)["sites"],observations)


def test_conformance_evidence_cannot_be_silently_replaced(tmp_path):
    sentinel=tmp_path/"existing";sentinel.write_bytes(b"immutable")
    with pytest.raises(SystemExit) as error:run.main(["--output",str(tmp_path)])
    assert error.value.code==2 and sentinel.read_bytes()==b"immutable"


def test_detector_timeout_is_a_product_failure_not_a_kit_pass(tmp_path,monkeypatch):
    path,template,case=case_named("arity-control")
    monkeypatch.setattr(run,"check",lambda *args:{"verdict":"valid","runtime":{"verdict":"valid"},"diagnostics":[]})
    def timeout(*args):raise subprocess.TimeoutExpired("installed-crosswire",90)
    monkeypatch.setattr(run,"invoke_detector",timeout)
    result=run.run_case(path,template,case,tmp_path/"result",sys.executable,sys.executable)
    assert result["status"]=="fail" and len(result["failures"])==3 and result["modes"]==3


def test_fast_installed_subprocess_subset_with_pinned_oracle(tmp_path):
    # CI installs --group eval explicitly; missing checker is a failure, not an
    # unnoticed skip. The complete 16-case kit remains a separate command.
    output=tmp_path/"kit"
    result=subprocess.run([sys.executable,"-m","conformance.run","--output",str(output),
                           "--case","rename-conflict","--case","arity-control"],
                          cwd=Path(__file__).parents[1],env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"},
                          capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
    summary=json.loads((output/"summary.json").read_text())
    assert summary["status"]=="partial" and summary["source_stable"]
    assert summary["case_count"]==2 and summary["oracle_states"]==8 and summary["mode_checks"]==6
    for case in summary["cases"]:
        assert case["status"]=="pass"
        assert (output/case["id"]/"rendered.json").exists() and (output/case["id"]/"oracle.json").exists()
